# Use workflow definitions to answer questions about how a configured process runs.
"""Answer process questions from the workflow definition and runtime conventions."""

import re

from .workflow_definition_repository import list_definitions, load_flow


# Test whether a message asks about how a workflow runs.
def is_process_question(message: str) -> bool:
    return bool(re.match(
        r"^(?:(?:please|(?:can|could|would) you)\s+)*(?:"
        r"(?:explain|describe|summari[sz]e|walk me through)\b|"
        r"(?:how (?:does|do|is|are|to)|what (?:does|do|is|are|happens|inputs|outputs|steps)|"
        r"when (?:does|do|is|are)|why (?:does|do|is|are))\b)",
        message.strip(), re.IGNORECASE,
    ))


# Choose a configured workflow that matches the process question.
def _select_flow(message: str):
    def words(text: str) -> str:
        return " ".join(word for word in re.findall(r"[\w]+", text.casefold())
                        if word not in {"a", "an", "the"})

    query = f" {words(message)} "
    matches = []
    for row in list_definitions():
        for alias in (row["flow"], row["name"]):
            name = words(alias)
            if name and f" {name} " in query:
                matches.append((len(name), row["flow"]))
    return load_flow(max(matches)[1]) if matches else None


# Turn one configured step into text describing what it does.
def _step_text(step: dict) -> str:
    kind = step["type"]
    fields = step.get("with")
    names = ", ".join(fields) if isinstance(fields, dict) else ""
    if kind == "api" and not step.get("action"):
        action = f"Calls the {step.get('toolName', step['id'])} API."
        params = step.get("parameters", {})
        if params:
            action += " Configured parameters include " + ", ".join(params) + "."
        mapping = step.get("responseMapping") or {}
        mappings = mapping.get("fields", [])
        if isinstance(mappings, list) and mappings:
            targets = [field["target"] for field in mappings if field.get("target")]
            if targets:
                action += " Reads these fields from the response: " + ", ".join(targets) + "."
    elif step.get("action") and kind in {"action", "api"}:
        action = f"Runs the {step['action']} action."
        if step["action"] == "require_non_empty_fields" and isinstance(fields, dict):
            values = fields.get("values") or {}
            if isinstance(values, dict) and values:
                action = f"Requires values for {', '.join(values)} before continuing."
        elif step["action"] == "generate_order_number":
            action = "Builds an order number using the configured prefix and date/time format."
        elif names:
            action += f" Passes {names} to the action."
    elif kind == "return":
        action = f"Returns {names} and stops the workflow." if names else "Returns the result and stops the workflow."
        if isinstance(fields, dict):
            for name, value in fields.items():
                if isinstance(value, dict) and value:
                    action += f" The {name} contains {', '.join(value)}."
    else:
        action = {
            "end": "Stops the workflow.",
            "condition": "Checks a condition and chooses the next step.",
            "flow": f"Runs the {step.get('flow') or step.get('flowId')} workflow.",
            "set": "Sets workflow variables.",
            "transform": "Transforms workflow data.",
            "display": "Prepares data for display.",
        }.get(kind, f"Runs a {kind} step.")
    if step.get("saveAs"):
        action += f" Saves the result as {step['saveAs']}."
    if kind not in {"return", "end"}:
        transitions = {"gotoStep": "Next", "onSuccess": "On success", "onTrue": "If true",
                       "onFalse": "If false", "onFailure": "On failure", "onError": "On error"}
        for key, label in transitions.items():
            target = step.get(key)
            if isinstance(target, dict):
                note = target.get("message")
                target = target.get("gotoStep")
                if note:
                    action += f" {label}, the configured message is “{note.strip()}”."
            if target:
                action += f" {label}, goes to {target}."
    return f"{step.get('name') or step['id']}. {action}"


# Return an explanation from the matched definition, or None if no match is found.
def explain_process(message: str) -> dict | None:
    flow = _select_flow(message)
    if flow is None:
        return None
    else:
        trigger = flow.get("trigger", {})
        lines = [f"{flow.get('name', flow['id'])} ({flow['id']})"]
        if trigger.get("ui"):
            lines.append(f"Starts when the {trigger['ui']} screen sends the {trigger.get('event', 'configured')} event.")
        if flow.get("inputs"):
            inputs = []
            for spec in flow["inputs"]:
                label = "required" if spec.get("required") else "optional"
                if spec.get("default") is not None:
                    label += f", defaults to {spec['default']}"
                inputs.append(f"{spec['name']} ({label})")
            lines.append("Inputs are " + ", ".join(inputs) + ".")
        for group in flow.get("inputGroups", []):
            if group.get("anyOf"):
                lines.append(f"Provide at least one of {', '.join(group['anyOf'])}.")
        batch = flow.get("batch") or {}
        if batch.get("input") and batch.get("maxItems") is not None:
            lines.append(f"The batch setting uses {batch['input']} and allows up to {batch['maxItems']} items.")
        lines.extend(f"{index}. {_step_text(step)}" for index, step in enumerate(flow.get("steps", []), 1))
        fallback = flow.get("errorHandling", {}).get("default", {})
        if isinstance(fallback, dict) and fallback.get("message"):
            lines.append(f"The default error message is “{fallback['message'].strip()}”")
        answer = "\n\n".join(lines)
    return {"success": True, "kind": "explanation", "needsInput": False,
            "assistantMessage": answer, "message": answer, "data": None}
