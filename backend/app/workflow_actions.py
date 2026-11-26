# Map workflow actions and API names to Python operations. PyYAML, xmltodict, and lxml support template and XML processing.
"""Allowlisted IBM Sterling workflow actions.

Live mode uses the Sterling InteropHttpServlet form contract.
Live Interop is required; demo/sample responses are disabled.
"""
import os
# Generate the random suffix used in newly created order numbers.
import secrets
from datetime import datetime
from pathlib import Path
# Read local service configuration from the backend environment file.
from dotenv import load_dotenv

# Preserve explicitly set environment variables when loading local defaults.
load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
# Match template placeholders and extract fields from text.
import re
# Use Python's ElementTree to read and traverse shared XML templates.
import xml.etree.ElementTree as ET
# Catch XML parse errors raised by xmltodict.
from xml.parsers.expat import ExpatError
from typing import Any

# Match template placeholders and extract fields from text.
import requests
from .runtime.xml_xpath import extract_xpath_values, parse_sample
from .runtime.prompt_transform import transform_with_prompt
# Use PyYAML to load workflow configuration.
import yaml
# Convert XML responses to Python mappings used by workflow expressions.
import xmltodict

# Expose the environment's mock-mode flag to application status callers.
MOCK_MODE = os.getenv("WORKFLOW_MOCK_MODE", "false").strip().lower() == "true"
# Resolve the URL for the Sterling interoperability endpoint.
INTEROP_URL = os.getenv(
    "INTEROP_URL",
    "http://localhost:9080/smcfs/interop/InteropHttpServlet",
).strip()
INTEROP_USER = os.getenv("INTEROP_USER", "").strip()
INTEROP_PASSWORD = os.getenv("INTEROP_PASSWORD", "")
XML_TEMPLATE_DIR = Path(__file__).resolve().parent / "definitions" / "templates"
XML_TEMPLATE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Capture a placeholder name from double-brace template syntax.
XML_TEMPLATE_VALUE = re.compile(r"\{\{([A-Za-z][A-Za-z0-9_]*)\}\}")


# Read workflow definitions to find configured interoperability calls.
def _interop_steps():
    from .runtime.workflow_definition_repository import DEFINITIONS, flow_definition_paths

    # Inspect the core YAML definitions for configured API steps.
    for path in flow_definition_paths(DEFINITIONS):
        try:
            flow = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError(f"Workflow definition is unavailable: {path.name}") from exc
        except yaml.YAMLError as exc:
            raise RuntimeError(f"Workflow definition is invalid: {path.name}") from exc
        # Skip empty YAML documents before checking their structure.
        if flow is None:
            continue
        if not isinstance(flow, dict) or not isinstance(flow.get("steps"), list):
            raise RuntimeError(f"Workflow definition must contain a steps list: {path.name}")
        # Filter workflow steps down to direct API calls and Sterling Flow calls.
        for step in flow["steps"]:
            if not isinstance(step, dict) or step.get("type") != "api":
                continue
            # Yield explicitly configured Flow invocations before checking API names.
            if (step.get("interop") or {}).get("type") == "flow":
                yield step
                continue
            if "toolName" not in step:
                continue
            api_name = step["toolName"]
            if not isinstance(api_name, str) or not api_name.strip():
                raise RuntimeError(f"Workflow contains an invalid toolName: {path.name}")
            yield step


# Return API names exposed by configured workflow steps.
def _enabled_api_names() -> set[str]:
    # Build the set of permitted API names from configured direct calls.
    return {step["toolName"] for step in _interop_steps() if (step.get("interop") or {}).get("type") != "flow"}


# Locate the requested template in the available definition roots.
def _find_template_file(relative: Path) -> Path:
    """Look in each definitions root (jar packs first, core last). A path starting with
    workflows/ is relative to the root; anything else is relative to its templates/ folder."""
    from .runtime.workflow_definition_repository import definition_roots
    # Search available pack and core roots in precedence order.
    for root in definition_roots():
        base = root.resolve()
        # Resolve a workflow-relative or template-relative file into an absolute path.
        candidate = (base / relative if relative.parts[0] == "workflows" else base / "templates" / relative).resolve()
        # Accept an existing XML file only when its resolved path stays within the definition root.
        if base in candidate.parents and candidate.suffix.lower() == ".xml" and candidate.is_file():
            return candidate
    raise ValueError(f"XML template not found: {relative.as_posix()}")


# Read a named XML template catalog into an ElementTree element.
def _read_xml_template(templateId: str) -> ET.Element:
    if not isinstance(templateId, str) or not templateId.strip():
        raise ValueError("XML template path is required")
    # Normalize separators before checking template path constraints.
    relative = Path(templateId.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("XML template path must stay inside the templates directory")
    # Allow callers to refer to a template by ID without the XML extension.
    if relative.suffix.lower() != ".xml":
        relative = relative.with_suffix(".xml")
    if any(not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", part) for part in relative.parts[:-1]) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.xml", relative.name):
        raise ValueError("XML template path must use lowercase kebab-case names")
    # Locate the allowed file before reading it as UTF-8.
    template_path = _find_template_file(relative)
    try:
        template = template_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise ValueError(f"XML template not found: {templateId}") from exc
    try:
        # Parse the template text into an element tree for inspection.
        return ET.fromstring(template)
    except ET.ParseError as exc:
        raise ValueError(f"XML template is invalid: {templateId}") from exc


# Find the selected entry and return its XML payload element.
def _get_xml_template_payload(templateId: str, contentId: str, wrapper: str) -> ET.Element:
    root = _read_xml_template(templateId)
    # Choose the expected outer catalog element for this request or response wrapper.
    catalog_root = {"Input": "InputTemplates", "Template": "OutputTemplates"}[wrapper]
    # Accept a standalone entry as well as an entry from a shared catalog.
    if root.tag == wrapper:
        templates = [root]
    elif root.tag == catalog_root:
        templates = list(root)
        if any(template.tag != wrapper for template in templates):
            raise ValueError(f"XML template catalog {templateId} contains an invalid entry")
        # Collect entry IDs so duplicates can be rejected before lookup.
        ids = [template.attrib.get("id") for template in templates]
        if len(ids) != len(set(ids)):
            raise ValueError(f"XML template catalog {templateId} contains duplicate IDs")
    else:
        raise ValueError(f"XML template {templateId} must use a {catalog_root} catalog")

    # Use the explicit entry ID when provided. Implicit selection requires exactly one entry.
    if contentId:
        templates = [template for template in templates if template.attrib.get("id") == contentId]
    elif len(templates) != 1:
        raise ValueError(f"XML template ID is required for catalog {templateId}")
    if len(templates) != 1:
        raise ValueError(f"XML template ID not found in {templateId}: {contentId}")
    selected = templates[0]
    if not selected.attrib.get("id"):
        raise ValueError(f"XML template {templateId} is missing its id")
    # Require exactly one XML payload inside the selected wrapper.
    children = list(selected)
    if len(children) != 1:
        raise ValueError(f"XML template {templateId} must contain exactly one payload")
    return children[0]


# Substitute input values into a parsed XML tree and return serialized XML.
def _render_xml_values(root, values: dict[str, Any], serialize) -> str:
    if not isinstance(values, dict):
        raise ValueError("XML template values must be a mapping")
    # Apply placeholder substitution to one XML text or attribute value.
    def render(value: str) -> str:
        def replace(match: re.Match[str]) -> str:
            # Read the configured variable name from the regex capture.
            name = match.group(1)
            # Fail early when a placeholder has no corresponding input.
            if name not in values:
                raise ValueError(f"XML template value is missing: {name}")
            resolved = values[name]
            # Convert a null value to empty text and stringify other values.
            return "" if resolved is None else str(resolved)

        return XML_TEMPLATE_VALUE.sub(replace, value)

    # Apply substitutions in text, tail text, and attributes throughout the parsed tree.
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        if element.text:
            element.text = render(element.text)
        if element.tail:
            element.tail = render(element.tail)
        for name, value in element.attrib.items():
            element.attrib[name] = render(value)
    # Serialize the edited tree so inserted values are escaped as XML.
    return serialize(root)


# Load a shared template and substitute the supplied values.
def _render_xml_template(templateId: str, values: dict[str, Any], contentId: str = "") -> str:
    root = _get_xml_template_payload(templateId, contentId, "Input")
    return _render_xml_values(root, values, lambda element: ET.tostring(element, encoding="unicode", short_empty_elements=True))


# Parse and render inline XML with a dictionary of values.
def render_inline_xml(xml: str, values: dict[str, Any]) -> str:
    from lxml import etree

    return _render_xml_values(parse_sample(xml), values, lambda element: etree.tostring(element, encoding="unicode", with_tail=False))


# Render request XML from a shared file ID and optional entry ID.
def render_xml_template(templateId: str, values: dict[str, Any], templateContentId: str = "") -> str:
    return _render_xml_template(templateId, values, templateContentId)


# Load and serialize a shared XML template without applying substitutions.
def load_xml_template(templateId: str, templateContentId: str = "") -> str:
    root = _get_xml_template_payload(templateId, templateContentId, "Template")
    return ET.tostring(root, encoding="unicode", short_empty_elements=True)


# Generate XML from a named template using the workflow arguments.
def generate_xml_from_template(
    templateId: str,
    values: dict[str, Any],
    templateContentId: str = "",
) -> str:
    return _render_xml_template(templateId, values, templateContentId)


# Read a trace-related error message from an XML response.
def _trace_error_message(xml: str) -> str:
    try:
        # Convert an error XML document into a mapping for message extraction.
        parsed = xmltodict.parse(xml)
    except ExpatError:
        return ""
    # Handle either a single Error entry or an Errors container.
    if "Error" in parsed:
        errors = parsed["Error"]
    elif "Errors" in parsed:
        errors = (parsed["Errors"] or {}).get("Error") if isinstance(parsed["Errors"], dict) else parsed["Errors"]
    else:
        return ""
    messages = []
    for error in errors if isinstance(errors, list) else [errors]:
        if isinstance(error, dict):
            # Try the ErrorDescription attribute, child field, and text in that order.
            message = error.get("@ErrorDescription") or error.get("ErrorDescription") or error.get("#text")
        else:
            message = error
        if isinstance(message, str) and message.strip():
            messages.append(message.strip())
    # Combine distinct response entries into a bounded message for the workflow.
    return " | ".join(messages)[:1500]


# Send the named Sterling API or service request with XML and return the integration result.
def post_interop(
    apiName: str,
    xmlPayload: str,
    templateXml: str = "",
    timeout: int = 60,
    serviceName: str = "",
) -> dict[str, Any]:
    """Post an XML request to Sterling Interop and return response XML + metadata.

    The XML payload is sent unchanged in InteropApiData. TemplateData is included
    only when the workflow provides a non-empty response template.
    """
    # Use service configuration when a service name is provided.
    if serviceName:
        if not any((step.get("toolName") or "") == apiName
                   and (step.get("interop") or {}).get("type") == "flow"
                   and step["interop"].get("serviceName") == serviceName for step in _interop_steps()):
            raise ValueError(f"Unsupported Interop flow: {serviceName}")
    # Check that a direct call matches an API declared in workflow YAML.
    elif not isinstance(apiName, str) or apiName not in _enabled_api_names():
        raise ValueError(f"Unsupported Interop API: {apiName}")

    try:
        # Verify the input is XML before submitting it to Sterling.
        xmltodict.parse(xmlPayload)
    except ExpatError as exc:
        raise ValueError(f"Invalid input XML: {exc}") from exc

    # Process an optional response template when the workflow supplies one.
    if templateXml:
        try:
            xmltodict.parse(templateXml)
        except ExpatError as exc:
            raise ValueError(f"Invalid template XML: {exc}") from exc

    # Stop execution when mock mode is requested. This action requires live Interop.
    if os.getenv("WORKFLOW_MOCK_MODE", "false").strip().lower() == "true":
        raise RuntimeError("Mock responses are disabled. Set WORKFLOW_MOCK_MODE=false and configure live Interop credentials.")

    # Check runtime configuration before creating the request.
    if not INTEROP_URL:
        raise RuntimeError("Interop URL is missing (INTEROP_URL)")
    if not INTEROP_USER or not INTEROP_PASSWORD:
        raise RuntimeError("Interop credentials are missing (INTEROP_USER / INTEROP_PASSWORD)")

    print(f"input xml: {xmlPayload[:500]}")  # log first 500 chars of input XML
    # Build the Interop form, including operation name, credentials, and the original XML body.
    form_data = {
        "YFSEnvironment.progId": "SterlingHttpTester",
        "InteropApiName": serviceName or apiName,
        "IsFlow": "Y" if serviceName else "N",
        "ServiceName": serviceName,
        "ApiName": apiName,
        "YFSEnvironment.userId": INTEROP_USER,
        "YFSEnvironment.password": INTEROP_PASSWORD,
        "InteropApiData": xmlPayload,
    }
    # Use service configuration when a service name is provided.
    if serviceName:
        # Include the extra form field required for a Sterling Flow invocation.
        form_data["InvokeFlow"] = "InvokeFlow"
    # Process an optional response template when the workflow supplies one.
    if templateXml:
        # Send the response template that controls the fields requested from Sterling.
        form_data["TemplateData"] = templateXml

    try:
        # Perform a synchronous form POST and pass the configured request timeout.
        response = requests.post(
            INTEROP_URL,
            data=form_data,
            timeout=timeout,
        )
        # Prefer Sterling's trace error message when the response includes one.
        if apiName == "modifyTrace" and (message := _trace_error_message(response.text)):
            raise RuntimeError(message)
        # Treat an HTTP error status as a failed integration request.
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not call IBM Sterling Interop: {exc}") from exc

    # Strip response whitespace before checking and returning the XML.
    raw_response = response.text.strip()
    print(f"interop response: {raw_response[:500]}")  # log first 500 chars of response XML     
    try:
        # Verify Sterling returned XML before passing raw text to the executor.
        parsed = xmltodict.parse(raw_response)
    except ExpatError as exc:
        # Do not return login pages or arbitrary HTML as if they were Interop data.
        excerpt = raw_response[:500]
        raise RuntimeError(
            f"Interop returned non-XML content (HTTP {response.status_code}): {excerpt}"
        ) from exc

    # Inspect the first XML root key for Sterling error envelopes.
    root_name = next(iter(parsed), "")
    if root_name in {"Error", "Errors"} or "Errors" in parsed:
        raise RuntimeError(f"IBM Sterling returned an error: {str(parsed)[:1500]}")

    return {
        "xml": raw_response,
        # Return transport status separately from the XML data.
        "http_status": response.status_code,
        "api_name": apiName,
        "mock_mode": False,
    }


# Use xmltodict to turn XML text into a mapping. The optional list config preserves collection fields.
def parse_xml_response(xml: str, forceList: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(xml, str) or not xml.strip():
        raise ValueError("XML response is empty")
    # Use forceList for element names that must stay lists even when only one item is present.
    return xmltodict.parse(xml, force_list=forceList or ())


# Select named fields from input records and return the projected list.
def project_records(records: Any, fields: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(fields, dict) or not all(
        isinstance(name, str) and isinstance(path, str) for name, path in fields.items()
    ):
        raise ValueError("Record projection fields must map names to paths")
    if records is None:
        return []
    # Treat one mapping as a single row so callers always receive a list.
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        raise ValueError("Records to project must be a list or mapping")

    projected = []
    for record in records:
        row = {}
        for name, path in fields.items():
            value = record
            # Traverse each dotted path. Missing fields become None in this projection.
            for segment in path.split("."):
                value = value.get(segment) if isinstance(value, dict) else None
            row[name] = value
        projected.append(row)
    return projected


# Remove the namespace prefix representation from an XML tag.
def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# Traverse the supported XML field path and return matching elements or scalar values.
def _xml_path_values(root: ET.Element, path: str) -> list[ET.Element | str | None]:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("XML paths must be non-empty strings")
    # Recognize the helper's limited recursive element selector.
    recursive = path.startswith("//")
    segments = [segment for segment in path.strip("/").split("/") if segment]
    if recursive:
        if len(segments) != 1 or segments[0].startswith("@"):
            raise ValueError(f"Recursive XML paths must select a single element name: {path}")
        return [
            node
            for node in root.iter()
            if _local_name(node.tag) == segments[0]
        ]
    # Allow a path to include the current root name or start at its children.
    if segments and segments[0] == _local_name(root.tag):
        segments.pop(0)
    if not segments:
        return [root]

    nodes = [root]
    for index, segment in enumerate(segments):
        # Read an attribute from the current nodes. It must be the final segment.
        if segment.startswith("@"):
            if index != len(segments) - 1 or len(segment) == 1:
                raise ValueError(f"XML attribute path must be the final path segment: {path}")
            return [node.attrib.get(segment[1:]) for node in nodes]
        nodes = [
            child
            for node in nodes
            for child in node
            if _local_name(child.tag) == segment
        ]
    return nodes


# Select XML records and map requested fields into dictionaries for workflow results.
def extract_xml_records(
    xml: str,
    recordPath: str,
    fields: dict[str, str],
    recordRequiredFields: list[str] | None = None,
) -> list[dict[str, str]]:
    if not isinstance(fields, dict) or not fields:
        raise ValueError("XML record fields must be a non-empty mapping")
    if not all(
        isinstance(name, str) and name and isinstance(path, str) and path
        for name, path in fields.items()
    ):
        raise ValueError("XML record fields must map non-empty names to paths")
    if recordRequiredFields is not None and (
        not isinstance(recordRequiredFields, list)
        or not all(isinstance(name, str) and name in fields for name in recordRequiredFields)
    ):
        raise ValueError("Required XML record fields must reference configured fields")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"Interop response XML could not be parsed: {exc}") from exc

    # Find the XML elements that represent output records.
    records = _xml_path_values(root, recordPath)
    if not all(isinstance(record, ET.Element) for record in records):
        raise ValueError("XML record path must select elements, not attributes")

    projected = []
    for record in records:
        row = {}
        for name, path in fields.items():
            values = _xml_path_values(record, path)
            # Reject ambiguous field paths so a row contains one value per field.
            if len(values) > 1:
                raise ValueError(f"XML field path selects multiple values: {path}")
            value = values[0] if values else None
            row[name] = (
                value.text or ""
                if isinstance(value, ET.Element)
                else str(value) if value is not None else ""
            )
        # Skip a record if a configured required field is blank.
        if recordRequiredFields and any(not row[name].strip() for name in recordRequiredFields):
            continue
        projected.append(row)
    return projected


# Apply configured Python regex patterns and return the captured values by field name.
def extract_regex_fields(
    text: str,
    patterns: dict[str, str | list[str]],
) -> dict[str, str]:
    if not isinstance(patterns, dict) or not all(
        isinstance(name, str) and name and
        (isinstance(value, str) or (
            isinstance(value, list) and all(isinstance(pattern, str) for pattern in value)
        ))
        for name, value in patterns.items()
    ):
        raise ValueError("Text extraction patterns must map field names to regex patterns")

    extracted = {}
    for name, configured in patterns.items():
        # Allow either one regex or a prioritized list for each field.
        candidates = [configured] if isinstance(configured, str) else configured
        for pattern in candidates:
            # Try the next pattern against the supplied text, ignoring case.
            match = re.search(pattern, text or "", re.IGNORECASE)
            if not match:
                continue
            # Use the named capture first and otherwise use the first numbered capture.
            if "value" in match.groupdict():
                extracted[name] = match.group("value")
            elif match.lastindex:
                extracted[name] = match.group(1)
            else:
                raise ValueError(f"Text extraction pattern for {name} must capture a value")
            break
    return extracted


# Return the input value when present or raise the supplied validation message.
def require_non_empty(value: Any, message: str) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(message)
    return value


# Return the supplied order number or generate one from the prefix and date format.
def generate_order_number(prefix: str, datetime_format: str, provided_order_no: str | None = None) -> str:
    # Use a supplied non-blank order number after trimming it.
    if provided_order_no is not None and provided_order_no.strip():
        return provided_order_no.strip()
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("Order number prefix is required")
    if not isinstance(datetime_format, str) or not datetime_format:
        raise ValueError("Order number datetime format is required")
    # Build a new order number from the prefix, local timestamp, and random hexadecimal suffix.
    return f"{prefix}{datetime.now().strftime(datetime_format)}{secrets.token_hex(4).upper()}"


# Validate a mapping of required values and return it for subsequent workflow steps.
def require_non_empty_fields(values: dict[str, Any], message: str) -> dict[str, Any]:
    if not isinstance(values, dict) or not values:
        raise ValueError("Configured order values must be a non-empty mapping")
    missing = [
        name
        for name, value in values.items()
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if missing:
        raise ValueError(f"{message}: {', '.join(missing)}")
    return values


# Expose the Python functions callable by name from workflow configuration.
ACTIONS = {
    "transform_with_prompt": transform_with_prompt,
    "extract_regex_fields": extract_regex_fields,
    "generate_order_number": generate_order_number,
    "generate_xml_from_template": generate_xml_from_template,
    "load_xml_template": load_xml_template,
    "render_xml_template": render_xml_template,
    "render_inline_xml": render_inline_xml,
    "post_interop": post_interop,
    "require_non_empty": require_non_empty,
    "require_non_empty_fields": require_non_empty_fields,
    "extract_xml_records": extract_xml_records,
    "extract_xpath_values": extract_xpath_values,
    "parse_xml_response": parse_xml_response,
    "project_records": project_records,
}
