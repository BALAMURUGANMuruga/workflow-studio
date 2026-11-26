# Take a feature description or sample XML and build draft workflow definitions. Uses PyYAML and lxml.
"""Generate validated workflow drafts from XML samples or saved templates."""

import re

import yaml
from lxml import etree

from .workflow_definition_repository import list_definitions, load_flow
from .workflow_validation import validate_flow
from .xml_xpath import evaluate_xpath, parse_sample


# Convert a field identifier into spaced words for matching against the request.
def _field_words(name: str) -> str:
    # Case-fold the text and remove punctuation, spaces, and underscores so Item ID and ItemID match.
    return re.sub(r"[\W_]+", "", name.casefold())


# Use the request text and sample XML to choose a matching XPath.
def _xml_selector(xml: str, request: str):
    # Parse and check the sample XML with the shared lxml parser.
    root = parse_sample(xml)
    # Track a generated XPath prefix for each namespace URI encountered.
    names = {}

    # Convert an expanded lxml name into an XPath-compatible local or prefixed name.
    def qualified_name(name: str) -> str:
        qualified = etree.QName(name)
        if not qualified.namespace:
            return qualified.localname
        # Reuse a prefix for the same namespace URI across the document.
        prefix = names.setdefault(qualified.namespace, f"ns{len(names) + 1}")
        return f"{prefix}:{qualified.localname}"

    # Index local names against concrete XPath candidates.
    fields: dict[str, set[str]] = {}
    paths = {}
    for node in root.iter(tag=etree.Element):
        # Build the node's path from the previously visited parent.
        parent_path = paths.get(node.getparent(), "")
        path = f"{parent_path}/{qualified_name(node.tag)}"
        paths[node] = path
        # Record the element path as a candidate for this local name.
        fields.setdefault(etree.QName(node.tag).localname, set()).add(path)
        for attribute in node.attrib:
            # Use the XPath attribute marker to select an attribute rather than an element.
            attr_path = f"{path}/@{qualified_name(attribute)}"
            fields.setdefault(etree.QName(attribute).localname, set()).add(attr_path)

    # Prefer an explicit XPath when it matches exactly one discovered path.
    explicit_paths = {path for paths in fields.values() for path in paths
                      if re.search(rf"(?<![\w/]){re.escape(path)}(?![\w/@:-])", request)}
    if len(explicit_paths) == 1:
        xpath = explicit_paths.pop()
        return root, xpath, {prefix: uri for uri, prefix in names.items() if f"{prefix}:" in xpath}

    # Focus on the part of the request that normally names the desired field.
    target = re.split(r"\b(?:from|in the|for each)\b", request, maxsplit=1, flags=re.I)[0]
    words = re.findall(r"[^\W_]+", target.casefold())
    # Join nearby words into candidates so multi-word names can match XML identifiers.
    phrases = {"".join(words[start:end]) for start in range(len(words))
               for end in range(start + 1, min(len(words), start + 6) + 1)}
    candidates = [name for name in fields if _field_words(name) in phrases]
    # Prefer compound field names, such as ItemID over Item or ID.
    candidates = [name for name in candidates if not any(
        _field_words(name) != _field_words(other) and _field_words(name) in _field_words(other)
        for other in candidates
    )]
    # Expand the selected field names into the actual XPath strings.
    selectors = {path for name in candidates for path in fields[name]}
    # Offer sample field names when the request did not match the XML.
    if not selectors:
        available = ", ".join(sorted(fields)[:12])
        raise ValueError(f"Name a field from the XML, for example {available}.")
    # Ask the caller to disambiguate when multiple paths could be selected.
    if len(selectors) != 1:
        raise ValueError(f"Several fields match. Specify one XPath: {', '.join(sorted(selectors)[:6])}.")
    xpath = selectors.pop()
    return root, xpath, {prefix: uri for uri, prefix in names.items() if f"{prefix}:" in xpath}


# Take a request and XML text. Return the XPath, matching values, and namespace metadata.
def inspect_xml(request: str, xml: str) -> dict:
    root, xpath, namespaces = _xml_selector(xml, request)
    # Run the selected XPath and return real sample values for the preview.
    values = evaluate_xpath(root, xpath, namespaces)
    return {"xpath": xpath, "namespaces": namespaces, "matches": len(values),
            "values": values[:100], "truncated": len(values) > 100}


# Build an extraction workflow and a preview from example XML.
def _xml_draft(request: str, xml: str) -> tuple[dict, dict]:
    # Reuse the tested expression and namespaces when building the workflow draft.
    preview = inspect_xml(request, xml)
    flow = {
        "id": "extract-xml-values",
        "name": "Extract XML Values",
        "version": "1.0",
        "description": "Extract values from the supplied XML using a verified XPath.",
        "trigger": {"type": "ui", "ui": "common-ui", "event": "execute"},
        "inputs": [{"name": "xml", "label": "Input XML", "type": "textarea", "required": True}],
        "steps": [
            {"id": "extract-values", "type": "action", "action": "extract_xpath_values",
             "with": {"xml": "${inputs.xml}", "xpath": preview["xpath"], "namespaces": preview["namespaces"]}, "saveAs": "extraction"},
            {"id": "show-result", "type": "return", "with": {"extraction": "${variables.extraction}"}},
        ],
    }
    return flow, preview


# Build a draft from the selected workflow template and natural-language request.
def _template_draft(request: str, template_id: str) -> tuple[dict, dict]:
    if not template_id:
        # Normalize the request before searching saved workflow names, APIs, and commands.
        compact_request = _field_words(request)
        matches = []
        for entry in list_definitions():
            flow = load_flow(entry["id"])
            apis = [step.get("toolName") for step in flow.get("steps", []) if step.get("type") == "api"]
            commands = (flow.get("ai") or {}).get("executionCommands") or []
            # Use workflow metadata and declared API names as template matching clues.
            labels = [entry["id"], entry["name"], *apis, *commands]
            if any(label and _field_words(label) in compact_request for label in labels):
                matches.append(entry["id"])
        if len(matches) != 1:
            raise ValueError("Choose a workflow template or name a single API used by an installed workflow.")
        template_id = matches[0]
    flow = load_flow(template_id)
    original_name = flow.get("name") or template_id
    flow["id"] = f"{template_id[:90].rstrip('-')}-draft"
    flow["name"] = f"{original_name} Draft"
    # Remove the original chat-routing metadata from the copy.
    flow.pop("ai", None)
    return flow, {"templateId": template_id, "apiCalled": False,
                  "note": "Template copied with its existing behavior. Generation does not apply custom API changes."}


# Choose the generation path and return the YAML draft with its preview.
def generate_workflow(request: str, xml: str, template_id: str) -> dict:
    if not request.strip():
        raise ValueError("Describe the workflow you want to generate.")
    # Reject conflicting sample XML and template input so the generation mode is explicit.
    if xml.strip() and template_id:
        raise ValueError("Use an XML sample or select a workflow template.")
    # Detect a trace configuration request before choosing the generic XML path.
    if not template_id and re.search(r"\bmodifyTrace\b|\btrace configuration\b", request, re.I):
        flow, preview = _trace_draft(request)
        code = _template_code(flow)
    elif xml.strip():
        flow, preview = _xml_draft(request, xml)
        code = _xml_code(preview)
    else:
        flow, preview = _template_draft(request, template_id)
        code = _template_code(flow)
    # Check the generated definition before serializing it for the designer.
    validate_flow(flow)
    return {"id": flow["id"], "yaml": yaml.safe_dump(flow, sort_keys=False, allow_unicode=True),
            "code": code, "preview": preview}


# Build trace configuration inputs, an API step, and a result step.
def _trace_draft(request: str) -> tuple[dict, dict]:
    # Find the Traces XML fragment embedded in the description.
    sample = re.search(r"<Traces\b.*?</Traces\s*>", request, re.S | re.I)
    # Parse the fragment and select its first direct Trace child.
    trace = parse_sample(sample.group()).find("Trace") if sample else None
    if trace is None:
        raise ValueError("Include a <Traces> sample with a <Trace> entry for modifyTrace.")
    # Normalize the trace type for validation while keeping the name for the form default.
    target_type = trace.get("Type", "API").upper()
    target_name = trace.get("Name", "").strip()
    if target_type not in {"API", "FLOW"} or not target_name:
        raise ValueError("The sample Trace must specify a Name and an API or Flow Type.")
    flow_type = trace.get("Type", "FLOW") if target_type == "FLOW" else "FLOW"
    level = trace.get("Level") or "VERBOSE"
    action = trace.get("Action") or "ADD"
    # Bind the generated form inputs to the shared modify-trace request template.
    parameters = {
        "action": action, "traceType": "${inputs.traceType}", "traceName": "${inputs.traceName}",
        "traceLevel": "${inputs.traceLevel}", "serverName": "${inputs.serverName}",
    }
    success = "Trace configuration updated successfully."
    flow = {
        "id": "trace-configuration",
        "name": "Trace Configuration",
        "version": "1.0",
        "description": "Set the trace level for a Sterling API or Flow.",
        "trigger": {"type": "ui", "ui": "common-ui", "event": "execute"},
        "successMessage": success,
        "inputs": [
            {"name": "traceType", "label": "Type", "type": "select", "required": True,
             "default": "API" if target_type == "API" else flow_type,
             "options": {"items": [{"label": "API", "value": "API"}, {"label": "Flow", "value": flow_type}]}},
            {"name": "traceName", "label": "Name", "type": "select", "required": True, "default": target_name,
             "options": {"dependsOn": "traceType", "traceTargets": True,
                         "byType": {"API" if target_type == "API" else flow_type: [{"label": target_name, "value": target_name}]}}},
            {"name": "traceLevel", "label": "Trace Level", "type": "string", "required": True, "default": level},
            {"name": "serverName", "label": "Server Name", "type": "string", "default": trace.get("ServerName", "")},
        ],
        "steps": [
            {"id": "modify-trace", "name": "Update trace configuration", "type": "api", "toolName": "modifyTrace",
             "xml_templates": {"request": {"id": "modify-trace"}},
             "parameters": parameters},
            {"id": "show-result", "type": "return", "with": {"message": success}},
        ],
    }
    return flow, {"api": "modifyTrace", "apiCalled": False, "requestXml": sample.group()}


# Return sample Python source that uses lxml to evaluate the generated XPath.
def _xml_code(preview: dict) -> str:
    return (
        "from pathlib import Path\nfrom lxml import etree\n\n"
        'xml = Path("input.xml").read_bytes()\n'
        "parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)\n"
        "root = etree.fromstring(xml, parser)\n"
        "if root.getroottree().docinfo.doctype:\n"
        '    raise ValueError("XML document type declarations are unsupported.")\n\n'
        f"matches = root.xpath({preview['xpath']!r}, namespaces={preview['namespaces']!r}, smart_strings=False)\n"
        'values = ["".join(value.itertext()) if isinstance(value, etree._Element) else str(value) for value in matches]\n'
        "print(values)\n"
    )


# Return sample Python source for invoking the generated workflow.
def _template_code(flow: dict) -> str:
    # Include the configured input defaults in the generated Python example.
    defaults = {field["name"]: field["default"] for field in flow["inputs"] if "default" in field}
    return (
        "import os\n"
        "import requests\n\n"
        'base_url = os.environ["WORKFLOW_STUDIO_URL"].rstrip("/")\n'
        'token = os.environ["WORKFLOW_STUDIO_TOKEN"]\n'
        f"inputs = {defaults!r}  # Supply workflow inputs here.\n\n"
        f'response = requests.post(f"{{base_url}}/api/execute/{flow["id"]}",\n'
        '    headers={"Authorization": f"Bearer {token}"}, json={"inputs": inputs}, timeout=60)\n'
        'response.raise_for_status()\n'
        'print(response.json())\n'
    )
