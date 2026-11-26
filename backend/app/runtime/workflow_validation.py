# Validate workflow mappings before execution so malformed steps, routes, and settings can be reported.
# Load YAML definitions by ID and import the ID reserved for the shared UI template.
from .workflow_definition_repository import COMMON_UI_ID, load_ui, load_flow
# ACTIONS maps configured action names to Python callables. Validation checks membership without calling them.
from ..workflow_actions import ACTIONS
# Reuse the runtime's lxml-based parser to check inline XML.
from .xml_xpath import parse_sample
# Use Python regular expressions to check the shape of XML source references.
import re

# Keep the accepted step types aligned with the branches in workflow_executor.py.
SUPPORTED_STEP_TYPES={"action","api","condition","set","transform","flow","display","return","end"}
# Check the UI definition before it is used. Raise ValueError when expected UI fields are missing.
def validate_ui(ui):
    # Reject a non-mapping, the wrong shared UI ID, or a workflow-specific flow reference. The or checks short-circuit.
    if not isinstance(ui, dict) or ui.get("id") != COMMON_UI_ID or "flow" in ui:
        # ValueError stops the caller from using this object as the shared UI template.
        raise ValueError("Shared UI YAML requires id: common-ui and has no flow reference")
    # An omitted components key defaults to an empty list. A present value must itself be a list.
    if not isinstance(ui.get("components",[]),list): raise ValueError("UI components must be a list")
    # True indicates validation completed successfully.
    return True

# Check workflow metadata, step types, configuration, and routing references. Raise ValueError on invalid definitions.
def validate_flow(flow):
    # Read optional configuration for chat intent selection.
    ai = flow.get("ai")
    # If the AI mapping declares a prompt, validate its type and reject whitespace-only text.
    if isinstance(ai, dict) and "prompt" in ai and (
        not isinstance(ai["prompt"], str) or not ai["prompt"].strip()
    ):
        # Report the error before the prompt is used by the selector.
        raise ValueError("AI prompt must be non-empty text")
    # Validate the execution allowlist only when the AI mapping declares it.
    if isinstance(ai, dict) and "executionCommands" in ai:
        # Read the configured command examples that chat can accept for execution.
        commands = ai["executionCommands"]
        # Require at least one command and check every item for non-empty text.
        if not isinstance(commands, list) or not commands or any(
            not isinstance(command, str) or not command.strip() for command in commands
        ):
            # Fail validation with a message that identifies the malformed allowlist.
            raise ValueError("AI executionCommands must be a non-empty list of commands")
    # Check for the four keys required by the workflow loader and executor.
    for key in ("id","version","inputs","steps"):
        # Report the first missing top-level key. Presence alone does not validate its contents.
        if key not in flow: raise ValueError(f"Flow YAML missing {key}")
    # Require the input definitions to be a list even for a workflow with zero form fields.
    if not isinstance(flow["inputs"],list): raise ValueError("Flow inputs must be a list")
    # Extract each mapping's name. Non-mapping entries are skipped here and detected by the length check below.
    input_names=[spec.get("name") for spec in flow["inputs"] if isinstance(spec,dict)]
    # Reject non-mapping entries, missing names, non-text names, and whitespace-only names.
    if len(input_names)!=len(flow["inputs"]) or any(not isinstance(name,str) or not name.strip() for name in input_names):
        raise ValueError("Each flow input must declare a name")
    # A set removes repeated names. A smaller set means two fields would use the same input key.
    if len(input_names)!=len(set(input_names)): raise ValueError("Flow input names must be unique")
    # Inspect each optional group that permits one of several named inputs.
    for group in flow.get("inputGroups",[]):
        # Require the group to be a mapping with a non-empty list of string names in anyOf.
        if (not isinstance(group,dict) or not isinstance(group.get("anyOf"),list)
                or not group["anyOf"] or not all(isinstance(name,str) for name in group["anyOf"])):
            raise ValueError("Each input group must declare a non-empty anyOf list")
        # Subtract declared names from the group's names to find references that cannot be resolved.
        unknown=set(group["anyOf"])-set(input_names)
        # Sort unknown names so the validation message is predictable.
        if unknown: raise ValueError(f"Input group references undeclared inputs: {', '.join(sorted(unknown))}")
    # Read the optional batch section. None means this validation block is skipped.
    batch=flow.get("batch")
    if batch is not None:
        # Reject a list or scalar because later code needs named batch settings.
        if not isinstance(batch,dict): raise ValueError("Batch configuration must be a mapping")
        # Require the batch input to name a declared workflow input.
        if batch.get("input") not in input_names: raise ValueError("Batch input must reference a declared workflow input")
        # Require a non-empty separator used when the executor splits batch values.
        if not isinstance(batch.get("separator"),str) or not batch["separator"]:
            raise ValueError("Batch separator must be a non-empty string")
        # Require a positive integer. Python bool is a subclass of int, so reject booleans explicitly.
        if not isinstance(batch.get("maxItems"),int) or isinstance(batch["maxItems"],bool) or batch["maxItems"] < 1:
            raise ValueError("Batch maxItems must be a positive integer")
        # Read the result projection that the executor uses for a batch.
        output=batch.get("output")
        # Require a named output collection and a non-empty mapping of projected fields.
        if (not isinstance(output,dict) or not isinstance(output.get("collection"),str)
                or not output["collection"].strip() or not isinstance(output.get("fields"),dict)
                or not output["fields"]):
            raise ValueError("Batch output must declare a collection and projected fields")
        # Check each projection entry. Keys name output fields and values identify paths in one execution result.
        if not all(
            isinstance(name,str) and name.strip() and isinstance(path,str) and path.strip()
            for name,path in output["fields"].items()
        ):
            raise ValueError("Batch output fields must map names to result paths")
    # Require a non-empty ordered list of steps.
    if not isinstance(flow["steps"],list) or not flow["steps"]: raise ValueError("Flow must contain steps")
    # Track IDs already encountered to detect duplicates.
    ids=set()
    # Collect all IDs before validating routes so a route can point forward.
    step_ids={step.get("id") for step in flow["steps"] if isinstance(step,dict)}
    # Inspect the steps in declared order. Each entry is expected to be a mapping.
    for step in flow["steps"]:
        # Reject duplicate IDs because jump targets must resolve to one step.
        if step.get("id") in ids: raise ValueError(f"Duplicate step ID: {step.get('id')}")
        # Remember the current ID before advancing to the next step.
        ids.add(step.get("id"))
        # Reject step types without an executor branch.
        if step.get("type") not in SUPPORTED_STEP_TYPES: raise ValueError(f"Unsupported step type: {step.get('type')}")
        # Require the action to name a registered Python callable.
        if step.get("type") == "action" and step.get("action") not in ACTIONS:
            raise ValueError(f"Action is not registered: {step.get('action')}")
        # Apply extra configuration checks to the rule-based transformation.
        if step.get("type") == "action" and step.get("action") == "transform_with_prompt":
            # Read the arguments that will be passed to the transform action.
            settings = step.get("with")
            # Require non-empty data and prompt strings plus a saveAs destination.
            if (not isinstance(settings, dict) or not isinstance(settings.get("data"), str)
                    or not settings["data"].strip() or not isinstance(settings.get("prompt"), str)
                    or not settings["prompt"].strip() or not step.get("saveAs")):
                raise ValueError(f"Prompt Transform step {step.get('id')} needs a data source, prompt, and output variable.")
        # API steps that invoke a registered action use the same action registry.
        if step.get("type") == "api" and step.get("action") and step.get("action") not in ACTIONS:
            raise ValueError(f"Action is not registered: {step.get('action')}")
        # Validate Sterling settings for declarative API steps.
        if step.get("type") == "api" and not step.get("action"):
            # Use an empty mapping when the step omits interop settings.
            invocation = step.get("interop") or {}
            # Require a mapping and accept api or flow. An omitted type defaults to api.
            if not isinstance(invocation, dict) or invocation.get("type", "api") not in ("api", "flow"):
                raise ValueError("Interop call type must be api or flow.")
            # A Sterling Flow uses serviceName instead of toolName.
            if invocation.get("type") == "flow":
                service = invocation.get("serviceName")
                # Reject a missing, non-text, or whitespace-only service name.
                if not isinstance(service, str) or not service.strip():
                    raise ValueError(f"Flow call {step.get('id')} requires a Service Name.")
            # Require toolName for a direct API call.
            elif not step.get("toolName"):
                raise ValueError(f"API step {step.get('id')} requires toolName")
            # Allow the default response handling, parsed JSON, or raw XML.
            if step.get("responseFormat") not in (None, "json", "xml"):
                raise ValueError("API response format must be json or xml.")
            # Read the request and response template configuration.
            templates = step.get("xml_templates") or {}
            # Check both request and response templates.
            for key in ("request", "response"):
                spec = templates.get(key) or {}
                # A source reference reuses XML available in the execution context.
                if "source" in spec:
                    source = spec["source"]
                    # Allow source only in requests. Require one complete expression rooted in inputs, variables, or steps.
                    if key != "request" or not isinstance(source, str) or not re.fullmatch(
                        r"\$\{(?:inputs|variables|steps)(?:\.[@\w-]+)+\}", source
                    # Reject a source combined with inline XML or a stored template reference.
                    ) or spec.get("xml") or spec.get("file") or spec.get("id"):
                        raise ValueError(f"API step {step.get('id')} requires one request XML source path.")
                # Validate inline XML before executing the API step.
                if "xml" in spec:
                    try:
                        # Apply the shared parser checks for XML size, syntax, and document type.
                        parse_sample(spec["xml"])
                    # Preserve the parse error as the cause and identify the failing step and template kind.
                    except ValueError as exc:
                        raise ValueError(f"API step {step.get('id')} has invalid {key} XML: {exc}") from exc
        # A subflow step needs the ID of the workflow it will invoke.
        if step.get("type") == "flow" and not (step.get("flow") or step.get("flowId")):
            raise ValueError(f"Flow step {step.get('id')} requires flow or flowId")
        # Validate named result settings only when displayAs is present.
        if step.get("type") == "display" and "displayAs" in step:
            # Read the output key used for the displayed result.
            label = step["displayAs"]
            # Require a non-blank label and a source or with value.
            if not isinstance(label, str) or not label.strip() or not (step.get("source") or step.get("with")):
                raise ValueError(f"Show Result step {step.get('id')} needs a result label and data source.")
        # Validate every supported success, failure, or decision route.
        for target in (step.get("gotoStep"), step.get("onTrue"), step.get("onFalse"), step.get("onSuccess"), step.get("onFailure"), step.get("onError")):
            # Read gotoStep when a route has additional settings in a mapping.
            if isinstance(target, dict): target = target.get("gotoStep")
            # Ignore unset targets and reject IDs that do not exist in this workflow.
            if target and target not in step_ids:
                raise ValueError(f"Step {step.get('id')} references unknown step: {target}")
    # Return True after all these checks pass.
    return True

# Input: UI ID and workflow ID. Output: the loaded pair if the workflow validation and link check pass.
def validate_pair(ui_id,flow_id):
    # Load the UI and workflow using the supplied identifiers.
    ui,flow=load_ui(ui_id),load_flow(flow_id)
    # Validate the workflow definition before checking the UI link.
    validate_flow(flow)
    # Require the UI reference to match the loaded workflow ID.
    if ui.get("flow") != flow.get("id"): raise ValueError("UI flow reference does not match Flow YAML ID")
    # Return the validated pair to the caller.
    return ui,flow
