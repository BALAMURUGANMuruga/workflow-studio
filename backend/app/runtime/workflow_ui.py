# Combine shared UI metadata with a workflow definition. Return form fields, choices, and presentation settings.
"""Compose the shared UI with metadata from the selected workflow."""

import re


# Combine a shared UI template and a workflow mapping. Return the assistant actions, form controls, and result metadata sent to Angular.
def build_workflow_ui(template: dict, flow: dict) -> dict:
    # Use the workflow label for display and fall back to the stable ID.
    name = flow.get("name") or flow["id"]
    # Normalize optional description text for the page header.
    description = (flow.get("description") or "").strip()
    ai = flow.get("ai") or {}
    # Prefer execution commands for quick actions and use example prompts as the fallback.
    prompts = ai.get("executionCommands") or ai.get("examples") or []
    # Copy assistant metadata so this workflow does not modify the shared template.
    assistant = dict(template.get("assistant", {}))
    presentation = flow.get("presentation") or {}
    if prompts:
        assistant["quickActions"] = [{"label": name, "prompt": prompts[0]}]
    # Explicitly configured quick actions take precedence over generated actions.
    if presentation.get("quickActions"):
        assistant["quickActions"] = presentation["quickActions"]

    fields = []
    # Copy workflow inputs and translate their types into Angular form controls.
    for spec in flow.get("inputs", []):
        # Copy this input's settings before normalizing them for the UI.
        field = dict(spec)
        # Derive a readable label from camelCase, underscores, or hyphens when none is supplied.
        field.setdefault("label", re.sub(r"(?<=[a-z0-9])(?=[A-Z])|[_-]", " ", spec["name"]).title())
        # Translate scalar definition types to Angular control names and preserve other declared control types.
        field["type"] = {"string": "text", "boolean": "checkbox", "integer": "number"}.get(
            spec.get("type"), spec.get("type") or "text")
        options = field.get("options") or {}
        # Build dependent trace choices from enabled APIs and registered workflow definitions.
        if options.get("traceTargets"):
            from .workflow_definition_repository import list_definitions
            from ..workflow_actions import _enabled_api_names

            # Keep manually configured targets for each trace type.
            existing = options.get("byType", {})
            # Build name-value pairs from the names of enabled APIs.
            api_targets = {name: name for name in sorted(_enabled_api_names())}
            # Use the workflow ID for submission and the workflow name for display.
            flow_targets = {item["id"]: item["name"] for item in list_definitions()}
            by_type = {}
            # Find the controlling dropdown using the dependsOn input name.
            type_spec = next((item for item in flow["inputs"] if item["name"] == options.get("dependsOn")), {})
            for choice in (type_spec.get("options") or {}).get("items", []):
                value = choice["value"]
                # Choose the API or workflow catalog based on the controlling option.
                targets = dict(api_targets if value == "API" else flow_targets)
                # Merge custom choices after discovered choices so custom labels can take precedence.
                targets.update({item["value"]: item["label"] for item in existing.get(value, [])})
                by_type[value] = [{"value": key, "label": label} for key, label in targets.items()]
            # Return the dependent choices alongside the original dropdown settings.
            field["options"] = {**options, "byType": by_type}
        fields.append(field)

    # Combine shared presentation components with workflow-specific result components.
    components = [*template.get("components", []), *presentation.get("results", [])]
    # Insert the generated form before the other shared UI components.
    if fields:
        components.insert(0, {"id": "workflow-inputs", "type": "form", "fields": fields})
    # Produce a new UI mapping with the workflow's title, form, and assistant actions.
    return {
        **template,
        "flow": flow["id"],
        "page": {**template.get("page", {}), "title": name, "description": description},
        "assistant": assistant,
        "components": components,
    }
