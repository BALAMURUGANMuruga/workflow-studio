# Read and update shared XML templates and preserve their IDs for workflow references. Uses PyYAML and lxml.
"""Reuse XML payloads in the shared request and response catalogs."""

import hashlib
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

import yaml
from lxml import etree

from .workflow_definition_repository import _safe_definition_path
from .xml_xpath import parse_sample

# Map each template kind to its shared filename, catalog root, and entry wrapper.
CATALOGS = {
    "request": ("input-templates", "InputTemplates", "Input"),
    "response": ("output-templates", "OutputTemplates", "Template"),
}
# Serialize in-process writes so catalog changes cannot overwrite one another.
CATALOG_LOCK = Lock()


# Take an XML element and return normalized bytes for comparing payloads. Fall back to serialized bytes if canonicalization fails.
def _fingerprint(element) -> bytes:
    # Compare parsed payloads after removing blank formatting nodes.
    parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False, no_network=True)
    # Reparse only the element and omit trailing text outside the payload.
    payload = etree.fromstring(etree.tostring(element, with_tail=False), parser)
    try:
        # Use canonical XML bytes without comments as the normal comparison form.
        return etree.tostring(payload, method="c14n", with_comments=False)
    # Use ordinary serialization if canonical XML cannot be produced.
    except etree.C14NError:
        return etree.tostring(payload, with_tail=False)


# Take catalog XML text and return an lxml root. Report malformed XML and document type declarations as ValueError.
def parse_template_catalog(xml: str):
    # Parse the catalog without external entities, DTD loading, or network access.
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    try:
        root = etree.fromstring(xml.encode("utf-8"), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Invalid XML template catalog.") from exc
    # Reject a catalog that declares a document type.
    if root.getroottree().docinfo.doctype:
        raise ValueError("XML template catalogs cannot contain document type declarations.")
    return root


# Take the template kind, payload text, and optional ID and name. Return the catalog file, resolved ID, display name, kind, and payload.
def save_catalog_template(kind: str, xml: str, *, template_id: str | None = None, name: str | None = None) -> dict:
    file, root_tag, wrapper_tag = CATALOGS[kind]
    # Validate the submitted payload before opening or updating the catalog.
    payload = parse_sample(xml)
    fingerprint = _fingerprint(payload)
    # Resolve the shared request or response catalog inside the definitions directory.
    path = _safe_definition_path(f"templates/{file}.xml")
    # Read, compare, and write the catalog under one in-process lock.
    with CATALOG_LOCK:
        # Load the existing text or start with an empty catalog of the expected kind.
        content = path.read_text(encoding="utf-8") if path.exists() else f"<{root_tag}>\n</{root_tag}>\n"
        root = parse_template_catalog(content)
        # Ensure a request payload is not added to a response catalog or vice versa.
        if root.tag != root_tag:
            raise ValueError(f"Invalid XML catalog: {file}")
        match = None
        # Collect IDs so a new entry cannot conflict with an existing one.
        reserved_ids = set()
        for entry in root:
            if entry.tag != wrapper_tag or not entry.get("id"):
                continue
            entry_id = entry.get("id")
            reserved_ids.add(entry_id)
            # Compare payload elements only, ignoring comments and other nodes in the wrapper.
            children = [node for node in entry if isinstance(node.tag, str)]
            # Compare normalized payload bytes to find existing templates with the same content.
            same_xml = len(children) == 1 and _fingerprint(children[0]) == fingerprint
            # Reject an explicitly requested ID that already points to different XML.
            if template_id == entry_id and not same_xml:
                raise FileExistsError(template_id)
            # Prefer the explicitly requested ID when several existing entries contain the same XML.
            if same_xml and (match is None or entry_id == template_id):
                match = entry
        # Return the existing reference when this payload is already stored.
        if match is not None:
            return {"file": file, "id": match.get("id"), "name": match.get("name") or match.get("id"),
                    "kind": kind, "xml": xml}

        if template_id is None:
            # Derive a repeatable ID for a payload that has no explicit ID.
            digest = hashlib.sha256(fingerprint).hexdigest()
            template_id = f"{kind}-{digest[:16]}"
            if template_id in reserved_ids:
                template_id = f"{kind}-{digest}"
            if template_id in reserved_ids:
                raise FileExistsError(template_id)
        # Create the catalog entry wrapper with its persistent template ID.
        wrapper = etree.Element(wrapper_tag, id=template_id)
        if name:
            wrapper.set("name", name)
        # Insert the parsed XML as a child element rather than as escaped text.
        wrapper.append(payload)
        entry_xml = etree.tostring(wrapper, encoding="unicode", with_tail=False)
        # Find the insertion point while preserving the existing catalog text.
        closing = content.rfind(f"</{root_tag}>")
        if closing < 0:
            raise ValueError(f"Missing closing tag in XML catalog: {file}")
        # Insert the new entry immediately before the shared catalog's closing tag.
        updated = content[:closing] + f"  {entry_xml}\n" + content[closing:]
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            # Write beside the catalog so the final replace stays on the same filesystem.
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                temp = Path(handle.name)
                handle.write(updated)
            # Replace the catalog only after the temporary file has been written and closed.
            temp.replace(path)
        # Clean up the temporary path after success or failure.
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        return {"file": file, "id": template_id, "name": name or template_id, "kind": kind, "xml": xml}


# Take original YAML and its parsed workflow. Save embedded payloads to the shared catalogs and return YAML with their IDs.
def externalize_workflow_xml(content: str, flow: dict) -> str:
    changed = False
    for step in flow.get("steps", []):
        if not isinstance(step, dict):
            continue
        templates = step.get("xml_templates")
        if not isinstance(templates, dict):
            continue
        # Inspect both request and response templates within each workflow step.
        for kind in CATALOGS:
            spec = templates.get(kind)
            if not isinstance(spec, dict) or "xml" not in spec:
                continue
            # Copy the template configuration before replacing its inline XML.
            spec = dict(spec)
            xml = spec.pop("xml")
            saved = save_catalog_template(kind, xml)
            # Use the shared catalog associated with the request or response kind.
            spec.pop("file", None)
            # Keep the other template options and write the saved catalog ID into the workflow.
            templates[kind] = {**spec, "id": saved["id"]}
            changed = True
    # Serialize updated YAML only if at least one inline template was externalized.
    return yaml.safe_dump(flow, sort_keys=False, allow_unicode=True) if changed else content
