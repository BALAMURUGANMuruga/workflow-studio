# Take a workflow ID and input mapping. Resolve references, run steps, and return result data and execution details.
"""YAML-driven workflow interpreter. Only registered Python actions can execute."""
import json
import time
from typing import Any
from ..workflow_actions import ACTIONS
from .workflow_definition_repository import load_flow
from .expression_resolver import TOKEN, resolve
from .workflow_validation import validate_flow
from .xml_xpath import parse_sample


# Validate declared inputs and apply defaults. Return the input mapping used at runtime.
def prepare_inputs(flow: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    specs = flow.get("inputs", [])
    declared = {spec["name"] for spec in specs if "name" in spec}
    unknown = set(inputs or {}) - declared
    if unknown:
        raise ValueError(f"Undeclared inputs: {', '.join(sorted(unknown))}")
    values = {spec["name"]: spec.get("default") for spec in specs if "name" in spec}
    values.update(inputs or {})
    for spec in specs:
        if spec.get("required") and values.get(spec["name"]) in (None, ""):
            raise ValueError(f"Required input missing: {spec['name']}")
    for group in flow.get("inputGroups", []):
        names = group.get("anyOf", [])
        if names and not any(values.get(name) not in (None, "") for name in names):
            raise ValueError(group.get("message") or f"Provide one of: {', '.join(names)}")
    return values


# Read the given expression against the current input, configuration, and variable context.
def _path(context: dict, expression: Any) -> Any:
    if not isinstance(expression, str):
        return resolve(expression, context)
    if expression.startswith("${") and expression.endswith("}"):
        return resolve(expression, context)
    current: Any = context
    for part in expression.removeprefix("$.").split("."):
        if isinstance(current, dict): current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current): current = current[int(part)]
        else: return None
    return current


# Evaluate the configured comparison and return the boolean used for branching.
def _condition(step: dict, context: dict) -> bool:
    spec = step.get("condition") or step.get("equals") or {}
    if "xmlField" in spec:
        field = spec["xmlField"]
        xml = resolve(field["source"], context)
        parse_sample(xml)
        left = _display_xml_value(ACTIONS["parse_xml_response"](xml=xml), field["path"])
        right = resolve(spec.get("right"), context)
        op = spec.get("operator", "equals")
    elif "left" in spec:
        left, right = resolve(spec.get("left"), context), resolve(spec.get("right"), context)
        op = spec.get("operator", "equals")
    else:
        left = _path(context, spec.get("field") or spec.get("path"))
        right = resolve(spec.get("value"), context)
        op = spec.get("operator", "notEmpty")
    if op in ("notEmpty", "not_empty"): return left not in (None, "", [], {})
    if op == "hasText": return isinstance(left, str) and bool(left.strip())
    if op in ("empty", "isEmpty"): return left in (None, "", [], {})
    if op in ("equals", "=="): return left == right
    if op in ("notEquals", "!="): return left != right
    if op == "contains": return right in left if left is not None else False
    if op == "in": return left in (right or [])
    if op == "truthy": return bool(left)
    if op == "greaterThan": return left is not None and right is not None and float(left) > float(right)
    raise ValueError(f"Unsupported condition operator: {op}")


# Resolve a display field from XML when the source is an XML value.
def _display_xml_value(value: Any, path: str) -> Any:
    if not path:
        return value
    key, _, tail = path.partition(".")
    if isinstance(value, dict):
        return _display_xml_value(value.get(key), tail)
    if isinstance(value, list):
        if key.isdigit():
            return _display_xml_value(value[int(key)], tail) if len(key) <= 9 and int(key) < len(value) else None
        return [_display_xml_value(item, path) for item in value]
    return None


# Build the named values that a display or return step exposes to the UI.
def _project_result_fields(step: dict, context: dict) -> dict:
    fields = step.get("with", {})
    if not isinstance(fields, dict):
        raise ValueError(f"Result step {step['id']} requires named fields.")
    output = {}
    for key, expression in fields.items():
        match = TOKEN.fullmatch(expression) if isinstance(expression, str) else None
        output[key] = _display_xml_value(context, match[1].strip()) if match else resolve(expression, context)
    parsed_sources = {}
    for key, spec in (step.get("xmlFields") or {}).items():
        source = spec["source"]
        if source not in parsed_sources:
            xml = resolve(source, context)
            parse_sample(xml)
            parsed_sources[source] = ACTIONS["parse_xml_response"](xml=xml)
        output[key] = _display_xml_value(parsed_sources[source], spec["path"])
    return output


# Run a definition step by step and track outputs and routes. Depth and permission flags apply to nested execution.
def _execute_flow(flow_id: str, inputs: dict[str, Any], depth: int = 0, *, can_modify_trace: bool = False) -> dict[str, Any]:
    # Limit recursive calls to subflows.
    if depth > 8: raise ValueError("Nested workflow depth exceeded")
    # Load the YAML definition by ID and validate it before starting.
    flow = load_flow(flow_id); validate_flow(flow)
    # Normalize values supplied by the chat or form.
    values = prepare_inputs(flow, inputs)
    # Copy configured initial variables into this execution.
    variables = dict(flow.get("variables") or {})
    # Expose the maps used by input, variable, config, and step expressions.
    context = {"inputs": values, "variables": variables, "config": flow.get("configuration", {}), "steps": {}}
    # Create the execution trace and start measuring duration.
    trace: list[dict[str, Any]] = []; started = time.perf_counter(); result = None
    # Collect fields explicitly sent to the result display.
    displayed: dict[str, Any] = {}
    # Collect text emitted by Show Message steps.
    messages: list[str] = []
    steps = flow["steps"]
    # Map step IDs to positions so jump targets do not require scanning the list.
    by_id = {step["id"]: index for index, step in enumerate(steps)}
    index = 0; iterations = 0
    # Walk the steps until execution stops or runs out of steps.
    while index < len(steps):
        iterations += 1
        # Stop execution when routing creates too many iterations.
        if iterations > 500: raise ValueError("Workflow step limit exceeded (possible loop)")
        step = steps[index]; step_id = step["id"]; kind = step["type"]
        # Record each visit in the trace and start timing that step.
        row = {"id": step_id, "type": kind, "status": "running"}; trace.append(row); tick = time.perf_counter()
        try:
            output = None; next_id = None; should_stop = False
            # Run the configured API, service, or registered legacy action.
            if kind == "api":
                if step.get("toolName") == "modifyTrace" and not can_modify_trace:
                    raise PermissionError("Master role required to modify trace configuration.")
                # Declarative Sterling Interop step: YAML selects catalogued API + XML templates.
                if step.get("action"):
                    fn = ACTIONS.get(step["action"])
                    if not fn: raise ValueError(f"Unregistered action: {step['action']}")
                    output = fn(**resolve(step.get("with", {}), context))
                else:
                    api_name = step.get("toolName") or ""
                    invocation = step.get("interop") or {}
                    service_name = invocation.get("serviceName") if invocation.get("type") == "flow" else None
                    templates = step.get("xml_templates") or {}
                    request_spec = templates.get("request") or {}
                    response_spec = templates.get("response") or {}
                    request_file = request_spec.get("file") or ("input-templates" if request_spec.get("id") else "")
                    response_file = response_spec.get("file") or ("output-templates" if response_spec.get("id") else "")
                    if not (api_name or service_name) or not (request_file or request_spec.get("xml") or request_spec.get("source")):
                        raise ValueError(f"Call step {step_id} requires a name and request XML")
                    # Resolve parameters using current workflow state before rendering XML.
                    params = resolve(step.get("parameters", {}), context)
                    # Reuse a previous XML value directly after validating it.
                    if request_spec.get("source"):
                        request_xml = resolve(request_spec["source"], context)
                        if not isinstance(request_xml, str):
                            raise ValueError(f"Call step {step_id} needs XML text at {request_spec['source']}.")
                        parse_sample(request_xml)
                    # Render an inline template with the resolved request parameters.
                    elif request_spec.get("xml"):
                        request_xml = ACTIONS["render_inline_xml"](xml=request_spec["xml"], values=params)
                    else:
                        request_xml = ACTIONS["render_xml_template"](
                            templateId=request_file, templateContentId=request_spec.get("id", ""), values=params)
                    response_xml_template = None
                    if response_spec.get("xml"):
                        response_xml_template = response_spec["xml"]
                    elif response_file:
                        response_xml_template = ACTIONS["load_xml_template"](
                            templateId=response_file, templateContentId=response_spec.get("id", ""))
                    invocation = step.get("interop") or {}
                    interop_options = {"serviceName": service_name} if service_name else {}
                    # Send the request XML and optional response template via the configured Sterling integration.
                    api_result = ACTIONS["post_interop"](
                        apiName=api_name, xmlPayload=request_xml,
                        timeout=step.get("timeout", flow.get("configuration", {}).get("timeout", 60)),
                        templateXml=response_xml_template, **interop_options)
                    xml = api_result.get("xml", "")
                    output_format = step.get("responseFormat")
                    # Keep raw XML when requested and parse other responses for mapping.
                    parsed = None if output_format == "xml" else ACTIONS["parse_xml_response"](xml=xml)
                    mapping = step.get("responseMapping") or {}
                    if output_format == "xml":
                        output = {"xml": xml}
                    # Project individual response paths into named result keys.
                    elif mapping.get("strategy") == "field":
                        output = {}
                        for field in mapping.get("fields", []):
                            source = field.get("source", ""); target_name = field.get("target")
                            if not target_name: continue
                            value = parsed
                            for part in str(source).removeprefix("$").lstrip(".").split(".") if source else []:
                                value = value.get(part) if isinstance(value, dict) else None
                            output[target_name] = value
                        if output_format != "json":
                            output.setdefault("raw", api_result)
                    elif output_format == "json":
                        output = {"response": parsed}
                    else:
                        output = {"response": parsed, "raw": api_result}
                target = step.get("saveAs") or step.get("output")
                # Make the step result available through variables in later steps.
                if target: variables[target] = output
            # Call a registered Python function with resolved arguments.
            elif kind == "action":
                action_name = step.get("action")
                fn = ACTIONS.get(action_name)
                if not fn: raise ValueError(f"Unregistered action: {action_name}")
                output = fn(**resolve(step.get("with", {}), context))
                target = step.get("saveAs") or step.get("output")
                # Make the step result available through variables in later steps.
                if target: variables[target] = output
            # Build values or project fields from the current context.
            elif kind == "set" or kind == "transform":
                mapping = step.get("values") or step.get("with") or {}
                output = _project_result_fields(step, context) if kind == "transform" and step.get("displayFields") else {
                    name: resolve(value, context) for name, value in mapping.items()
                }
                if step.get("saveAs"): variables[step["saveAs"]] = output
                else: variables.update(output)
            # Evaluate a decision and choose the true or false route.
            elif kind == "condition":
                matched = _condition(step, context)
                row["condition"] = matched
                if step.get("saveAs"): variables[step["saveAs"]] = matched
                next_id = step.get("onTrue" if matched else "onFalse") or step.get("onSuccess" if matched else "onFailure")
                if isinstance(next_id, dict): next_id = next_id.get("gotoStep")
                if not matched and not next_id and step.get("onError"):
                    handler = step["onError"]; next_id = handler.get("gotoStep") if isinstance(handler, dict) else handler
            # Resolve child inputs and execute another workflow within this run.
            elif kind == "flow":
                child_id = step.get("flow") or step.get("flowId")
                if not child_id: raise ValueError(f"Flow step {step_id} requires flow/flowId")
                child_inputs = resolve(step.get("inputs", step.get("with", {})), context)
                output = _execute_flow(child_id, child_inputs, depth + 1, can_modify_trace=can_modify_trace)
                if not output.get("success"): raise RuntimeError(output.get("detail") or output.get("message"))
                if step.get("saveAs"): variables[step["saveAs"]] = output.get("data")
                row["childSteps"] = output.get("steps", [])
            # Resolve data for the result panel or format it as a chat message.
            elif kind == "display":
                if step.get("displayFields"):
                    output = _project_result_fields(step, context)
                    displayed.update(output)
                else:
                    output = resolve(step.get("with", step.get("source", {})), context)
                if step.get("saveAs"): variables[step["saveAs"]] = output
                if step.get("displayAs"): displayed[step["displayAs"]] = output
                if step.get("presentation") == "message":
                    if isinstance(output, str):
                        if output.strip(): messages.append(output)
                    elif output is not None:
                        messages.append(json.dumps(output, ensure_ascii=False, indent=2, default=str))
            # Build the final response data and request a stop.
            elif kind == "return":
                result = _project_result_fields(step, context) if step.get("displayFields") else resolve(step.get("with", {}), context)
                should_stop = True
            # Finish execution and mark the final step complete.
            elif kind == "end":
                row["status"] = "completed"; row["duration_ms"] = round((time.perf_counter()-tick)*1000, 2); break
            else: raise ValueError(f"Unsupported step type: {kind}")
            # Expose non-null output through the step ID as well as any configured saveAs variable.
            if output is not None: context["steps"][step_id] = {"result": output}
            context["variables"] = variables
            row["status"] = "completed"
            target = step.get("onSuccess")
            if isinstance(target, dict): target = target.get("gotoStep")
            # Prefer the route chosen by the step, then an explicit jump or success route.
            next_id = next_id or step.get("gotoStep") or target
            row["duration_ms"] = round((time.perf_counter()-tick)*1000, 2)
            if should_stop: break
            if next_id:
                if next_id not in by_id: raise ValueError(f"Step {step_id} references unknown gotoStep: {next_id}")
                index = by_id[next_id]; continue
        # Record the failure and route to an error handler when configured.
        except Exception as exc:
            row["status"] = "failed"; row["error"] = str(exc)
            handler = step.get("onError") or flow.get("errorHandling", {}).get("default", {})
            if isinstance(handler, dict) and handler.get("gotoStep") in by_id:
                row["message"] = handler.get("message", str(exc)); row["duration_ms"] = round((time.perf_counter()-tick)*1000, 2)
                context["error"] = {"message": str(exc), "step": step_id}; index = by_id[handler["gotoStep"]]; continue
            message = handler.get("message", str(exc)) if isinstance(handler, dict) else str(exc)
            return {"success": False, "flow": flow_id, "message": message, "detail": str(exc), "data": None,
                    "variables": variables, "steps": trace, "durationMs": round((time.perf_counter()-started)*1000, 2)}
        # Continue to the following step when there is no jump.
        index += 1
    # Merge displayed fields into the result returned to the UI.
    if displayed:
        result = {**displayed, **result} if isinstance(result, dict) else (
            {**displayed, "result": result} if result is not None else {**variables, **displayed}
        )
    return {"success": True, "flow": flow_id, "message": "\n".join(messages) or flow.get("successMessage") or "Flow completed", "data": result if result is not None else variables,
            "variables": variables, "steps": trace, "durationMs": round((time.perf_counter()-started)*1000, 2)}


# Run a single workflow and return the execution result.
def execute(flow_id: str, inputs: dict[str, Any], *, can_modify_trace: bool = False):
    return _execute_flow(flow_id, inputs, can_modify_trace=can_modify_trace)


# Run once or execute the configured batch. Return an aggregate result for a batch.
def execute_with_batch(flow_id: str, inputs: dict[str, Any], *, can_modify_trace: bool = False) -> dict[str, Any]:
    # Load the YAML definition by ID and validate it before starting.
    flow = load_flow(flow_id); validate_flow(flow); batch = flow.get("batch")
    if not isinstance(batch, dict): return execute(flow_id, inputs, can_modify_trace=can_modify_trace)
    input_name, separator = batch["input"], batch["separator"]; raw_value = inputs.get(input_name)
    if not isinstance(raw_value, str) or separator not in raw_value: return execute(flow_id, inputs, can_modify_trace=can_modify_trace)
    values = [value.strip() for value in raw_value.split(separator)]
    if any(not value for value in values): raise ValueError(f"Each value for {input_name} must be non-empty")
    if len(values) > batch["maxItems"]: raise ValueError(f"A maximum of {batch['maxItems']} values is allowed per request")
    output = batch["output"]; results=[]; successful=0; duration_ms=0.0
    for value in values:
        item_inputs=dict(inputs); item_inputs[input_name]=value
        try: current=execute(flow_id,item_inputs,can_modify_trace=can_modify_trace)
        except (FileNotFoundError,RuntimeError,ValueError) as exc: current={"success":False,"message":str(exc),"detail":str(exc)}
        ok=current.get("success") is True; successful += int(ok); duration_ms += current.get("durationMs",0)
        row={name: _batch_field_value(current,value,path) for name,path in output["fields"].items()}
        row["lookupStatus"]="Retrieved" if ok else "Failed"; row["error"]=None if ok else current.get("detail") or current.get("message"); results.append(row)
    failed=len(results)-successful
    return {"success":successful>0,"batch":True,"partialSuccess":successful>0 and failed>0,"flow":flow_id,
            "message":f"Order lookup complete: {successful} succeeded, {failed} failed.","data":{output["collection"]:results},"durationMs":round(duration_ms,2)}


# Read a configured path from one run to populate the batch output.
def _batch_field_value(result: dict[str, Any], input_value: str, path: str) -> Any:
    if path == "input": return input_value
    value: Any=result
    for segment in path.split("."): value=value.get(segment) if isinstance(value,dict) else None
    return value
