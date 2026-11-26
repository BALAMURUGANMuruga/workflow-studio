# Route chat requests to Python handlers, local workflow selection, or document answers.
# Inputs arrive from the FastAPI chat route. Outputs are dictionaries consumed by the Angular UI.
# Python re and difflib handle pattern matching and suggestions. JSON formats XML extraction results.
# Workflow retrieval and document RAG are implemented in assistant_ai and called through service functions.
import json
import re
from difflib import get_close_matches
from typing import Any

from .workflow_definition_repository import COMMON_UI_ID, list_flow_ids, load_flow, load_ui
from ..assistant_ai.workflow_intent_service import LocalModelError, select_workflow
from ..assistant_ai.document_assistant.document_service import answer_document_question
from ..assistant_ai.document_assistant.document_retrieval import is_simple_greeting
from .workflow_validation import validate_flow
from .workflow_executor import execute_with_batch, prepare_inputs
from .workflow_explainer import explain_process, is_process_question
from .workflow_ui import build_workflow_ui
from .workflow_generator import inspect_xml


# Represents a configuration problem that callers can report as an AI service error.
class AIConfigurationError(RuntimeError):
    pass


# Signals a failed inference call or an invalid response from the local selector.
class AIProviderError(RuntimeError):
    pass


# Load the shared UI and workflow YAML. Return validated, AI-enabled workflows and their UI by ID.
def _available_workflows() -> dict[str, dict[str, Any]]:
    workflows: dict[str, dict[str, Any]] = {}
    template = load_ui(COMMON_UI_ID)
    for flow_id in list_flow_ids():
        flow = load_flow(flow_id)
        ai = flow.get("ai", {})
        if not isinstance(ai, dict) or ai.get("enabled") is not True:
            continue
        validate_flow(flow)
        workflows[flow["id"]] = {"ui": build_workflow_ui(template, flow), "flow": flow}
    if not workflows:
        raise ValueError("No AI-enabled workflow definitions are available")
    return workflows


# Take the enabled workflows and their UI. Return metadata, example prompts, and input definitions for local selection.
def _catalog_for_model(workflows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    catalog = []
    for flow_id, pair in workflows.items():
        flow = pair["flow"]
        ui = pair["ui"]
        fields = {}
        for component in ui.get("components", []):
            for field in component.get("fields", []):
                fields[field.get("name")] = field
        ai = flow.get("ai", {})
        inputs = []
        for spec in flow.get("inputs", []):
            name = spec["name"]
            field = fields.get(name, {})
            inputs.append({
                "name": name,
                "type": spec.get("type"),
                "required": spec.get("required", False),
                "default": spec.get("default"),
                "clarification": spec.get("clarification"),
                "label": field.get("label", name),
                "help": field.get("help", ""),
                "placeholder": field.get("placeholder", ""),
            })
        catalog.append({
            "id": flow_id,
            "name": flow.get("name", flow_id),
            "description": flow.get("description", ""),
            "intent": ai.get("intent", ""),
            "prompt": ai.get("prompt", ""),
            "examples": ai.get("examples", []),
            "executionCommands": ai.get("executionCommands", []),
            "clarification": ai.get("clarification"),
            "inputs": inputs,
            "inputGroups": flow.get("inputGroups", []),
            "batch": flow.get("batch"),
        })
    return catalog


# Send the current message, catalog, and active turns to the local selector. Return its workflow ID, extracted inputs, and clarification.
def _select_local_workflow(
    message: str,
    catalog: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        return select_workflow(message, catalog, history)
    except LocalModelError as exc:
        raise AIProviderError(f"Local model inference failed: {exc}") from exc


# Keep recent turns only while the assistant is waiting for an input to a pending workflow.
def _active_chat_history(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not history or not isinstance(history[-1], dict):
        return []
    pending = history[-1]
    if pending.get("needsInput") is not True or not pending.get("flow"):
        return []
    start = 0
    for index, turn in enumerate(history[:-1]):
        if isinstance(turn, dict) and turn.get("role") == "assistant" and turn.get("needsInput") is not True:
            start = index + 1
    return [turn for turn in history[start:] if isinstance(turn, dict)]


# Check required input groups and individual fields. Return a clarification and optional field name when a value is missing.
def _missing_input(flow: dict[str, Any], inputs: dict[str, Any]) -> tuple[str, str | None] | None:
    for group in flow.get("inputGroups", []):
        names = group.get("anyOf", [])
        if names and not any(inputs.get(name) not in (None, "") for name in names):
            return (
                group.get("message") or f"Provide one of: {', '.join(names)}",
                None,
            )
    for spec in flow.get("inputs", []):
        name = spec.get("name")
        if (
            spec.get("required")
            and name
            and inputs.get(name) in (None, "")
            and spec.get("default") in (None, "")
        ):
            return (
                spec.get("clarification") or f"Please provide {name}.",
                name,
            )
    return None


# Build a response the UI can render as a question, with optional workflow form metadata.
def _needs_input(
    message: str,
    flow_id: str | None = None,
    ui: dict[str, Any] | None = None,
    input_name: str | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "success": False,
        "needsInput": True,
        "flow": flow_id,
        "inputName": input_name,
        "message": message,
        "assistantMessage": message,
        "data": None,
    }
    if ui is not None:
        response.update({"uiId": ui["id"], "ui": ui})
    return response


# Use the caller's role and saved workflows to return trace configuration guidance or a generator shortcut.
def _trace_configuration_reply(is_master: bool) -> dict[str, Any]:
    if not is_master:
        text = "A master user can apply trace configuration from the saved workflow."
        return {"kind": "explanation", "assistantMessage": text}
    choices = []
    for flow_id in list_flow_ids():
        flow = load_flow(flow_id)
        if any(isinstance(step, dict) and step.get("type") == "api" and step.get("toolName") == "modifyTrace"
               for step in flow.get("steps", [])):
            choices.append({"id": flow_id, "name": flow.get("name") or flow_id})
    if choices:
        return {
            "kind": "explanation", "traceWorkflows": choices,
            "assistantMessage": "Open a trace workflow and review the type, name, and trace level. Select Run selected workflow to apply the configuration.",
        }
    return {
        "kind": "explanation", "openTraceGenerator": True,
        "assistantMessage": "Save a trace configuration workflow in the YAML generator first. Then open it to review and apply the trace.",
    }


# Find XML and an extraction request in one message. Return XPath, match count, and values if the request is supported.
def _inline_xml_reply(message: str) -> dict[str, Any] | None:
    start = re.search(r"<[\w?!]", message)
    end = message.rfind(">")
    if not start or end < start.start():
        return None
    request = (message[:start.start()] + " " + message[end + 1:]).replace("```xml", "").replace("```", "").strip()
    if not re.match(r"^(?:please\s+)?(?:get|extract|select|show|find|read)\b", request, re.I):
        return None
    try:
        extraction = inspect_xml(request, message[start.start():end + 1])
    except ValueError as exc:
        return {"kind": "explanation", "assistantMessage": str(exc)}
    lines = [
        f"XPath: {extraction['xpath']}",
        f"Matches: {extraction['matches']}",
        f"Values: {json.dumps(extraction['values'], ensure_ascii=False)}",
    ]
    if extraction["namespaces"]:
        lines.append("Namespaces: " + json.dumps(extraction["namespaces"], ensure_ascii=False))
    if extraction["truncated"]:
        lines.append("Showing the first 100 values.")
    return {"kind": "explanation", "assistantMessage": "\n".join(lines), "extraction": extraction}


# Take chat text, optional message history, and a role flag. Return a workflow result, clarification, or document answer.
def process_chat_message(
    message: str,
    history: list[dict[str, Any]] | None = None,
    *,
    is_master: bool = False,
) -> dict[str, Any]:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("A chat message is required")
    message = message.strip()
    # Keep only the context needed to resume a pending workflow.
    active_history = _active_chat_history(history)
    question = message.casefold().rstrip("?!.")
    if re.match(r"^(?:please\s+)?(?:apply|configure|enable|modify|set|update)\s+"
                r"(?:(?:the|a)\s+)?trac(?:e|ing)\b", question):
        return _trace_configuration_reply(is_master)
    asks_name = re.fullmatch(r"what(?: is|'s) your name|(?:you|your) name|who are you|what are you called", question)
    if not active_history or asks_name:
        asks_purpose = re.fullmatch(r"what are you doing(?: here)?|what (?:can|do) you do|how can you help(?: me)?", question)
        if asks_name or asks_purpose or is_simple_greeting(message):
            profile = load_ui(COMMON_UI_ID)["assistant"]
            context = profile["name"] if asks_name else profile["purpose"]
            if not (asks_name or asks_purpose):
                context = f"{profile['name']}\n\n{context}"
            return answer_document_question(message, history, assistant_context=context)
    # Explicitly route document questions to retrieval and answer generation.
    if message.casefold().startswith("ask docs:"):
        return answer_document_question(message.split(":", 1)[1], history)
    # Handle XML extraction using Python rules and XPath before selecting a workflow.
    xml_reply = _inline_xml_reply(message)
    if xml_reply is not None:
        return xml_reply
    if is_process_question(message):
        explanation = explain_process(message)
        return explanation if explanation is not None else answer_document_question(message, history)
    # Build the catalog consumed by the local AI workflow selector.
    workflows = _available_workflows()
    catalog = _catalog_for_model(workflows)
    selection = _select_local_workflow(message.strip(), catalog, active_history)
    # Validate the selector response before using its fields.
    if not {"flowId", "inputs", "clarification"}.issubset(selection):
        raise AIProviderError("The local model returned an invalid response")

    flow_id = selection["flowId"]
    clarification = selection["clarification"]
    if flow_id is not None and not isinstance(flow_id, str):
        raise AIProviderError("The local AI returned an invalid workflow ID")
    if clarification is not None and not isinstance(clarification, str):
        raise AIProviderError("The local AI returned an invalid clarification")
    if flow_id is None:
        if not active_history:
            return answer_document_question(message, history)
        if not clarification or not clarification.strip():
            raise AIProviderError("The local AI did not provide a clarification")
        return _needs_input(clarification.strip())
    if flow_id not in workflows:
        raise AIProviderError("The local AI selected a workflow that is not available")

    pair = workflows[flow_id]
    flow = pair["flow"]
    ui = pair["ui"]
    ai = flow.get("ai", {})
    # Apply the configured command gate before executing a workflow.
    commands = ai.get("executionCommands")
    if commands is not None:
        initial_request = next(
            (turn["content"] for turn in active_history
             if turn.get("role") == "user" and isinstance(turn.get("content"), str)),
            message,
        )
        command = " ".join(initial_request.partition(":")[0].casefold().split()).rstrip(".!")
        configured_commands = {" ".join(text.casefold().split()) for text in commands}
        allowed = command in configured_commands
        if not allowed and ai.get("allowInlineCommandInputs") is True:
            allowed = any(command.startswith(f"{prefix} ") for prefix in configured_commands)
        if not allowed:
            same_action = [candidate for candidate in sorted(configured_commands)
                           if candidate.partition(" ")[0] == command.partition(" ")[0]]
            close = get_close_matches(command, same_action, n=1, cutoff=0.84)
            if close:
                suggestion = close[0]
                return _needs_input(
                    f"Did you mean {flow.get('name', flow_id)}? To continue, send “{suggestion}”."
                )
            return answer_document_question(message, history)
    # Validate extracted values against the workflow's declared input schema.
    extracted = selection["inputs"]
    if not isinstance(extracted, dict):
        raise AIProviderError("The local AI returned invalid workflow inputs")
    declared = {spec["name"] for spec in flow.get("inputs", [])}
    unexpected = set(extracted) - declared
    if unexpected:
        raise AIProviderError(
            f"The local AI returned undeclared inputs: {', '.join(sorted(unexpected))}"
        )
    if any(value is not None and not isinstance(value, (str, int, float, bool)) for value in extracted.values()):
        raise AIProviderError("Workflow inputs must be scalar values")
    input_specs = {spec["name"]: spec for spec in flow.get("inputs", [])}
    for name, value in extracted.items():
        if value is None:
            continue
        input_type = input_specs[name].get("type")
        if input_type == "string":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                extracted[name] = str(value)
            elif not isinstance(value, str):
                raise AIProviderError(f"The local AI returned an invalid value for {name}")
        elif input_type == "boolean" and not isinstance(value, bool):
            raise AIProviderError(f"The local AI returned an invalid value for {name}")
        elif input_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            raise AIProviderError(f"The local AI returned an invalid value for {name}")

    # Check that extracted text values appear in the user turns used for this run.
    user_evidence = " ".join(
        [
            turn["content"]
            for turn in active_history
            if turn.get("role") == "user" and isinstance(turn.get("content"), str)
        ]
        + [message.strip()]
    ).casefold()
    for name, value in extracted.items():
        if isinstance(value, str) and value and value.casefold() not in user_evidence:
            raise AIProviderError(f"The local AI returned an input not present in the current message: {name}")

    # Ask for missing values before calling the workflow executor.
    missing_input = _missing_input(flow, extracted)
    if missing_input is not None:
        clarification_text, input_name = missing_input
        return _needs_input(clarification_text, flow_id, ui, input_name)
    if clarification:
        return _needs_input(clarification, flow_id, ui)

    try:
        # Apply runtime defaults and normalize input values before execution.
        inputs = prepare_inputs(flow, extracted)
    except ValueError as exc:
        return _needs_input(str(exc), flow_id, ui)

    try:
        # Run the selected workflow and handle batch requests through the same executor.
        result = execute_with_batch(flow_id, inputs)
    except ValueError as exc:
        return _needs_input(str(exc), flow_id, ui)
    result["uiId"] = ui["id"]
    result["ui"] = ui
    if result.get("batch"):
        result["assistantMessage"] = result["message"]
    else:
        result["assistantMessage"] = (
            flow.get("ai", {}).get("successMessage", result.get("message", "Workflow completed"))
            if result.get("success")
            else result.get("message", "Workflow execution failed")
        )
    return result
