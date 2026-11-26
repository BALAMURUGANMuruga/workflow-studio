# Expose YAML draft generation, XML inspection, and workflow designer operations.
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
import yaml
from lxml import etree

from ..auth.authentication_routes import get_current_user, require_master
from ..runtime.workflow_definition_repository import definition_roots, save_generated_workflow
from ..runtime.workflow_generator import generate_workflow
from ..runtime.workflow_validation import SUPPORTED_STEP_TYPES, validate_flow
from ..runtime.workflow_xml_storage import externalize_workflow_xml, parse_template_catalog, save_catalog_template
from ..runtime.xml_xpath import parse_sample
from ..workflow_actions import ACTIONS, parse_xml_response

router = APIRouter(prefix="/api")


class WorkflowDraftBody(BaseModel):
    request: str = Field(min_length=1, max_length=12000)
    xml: str = Field(default="", max_length=200_000)
    templateId: str = Field(default="", max_length=128)


@router.post("/studio/generate", dependencies=[Depends(get_current_user)])
def create_draft(body: WorkflowDraftBody):
    try:
        return generate_workflow(body.request, body.xml, body.templateId)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Workflow template was not found.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class ConfirmWorkflowBody(BaseModel):
    yaml: str = Field(min_length=1, max_length=250_000)


class DesignerWorkflowBody(BaseModel):
    workflow: dict[str, Any]


class DesignerXmlBody(BaseModel):
    xml: str = Field(min_length=1, max_length=200_000)


class SaveDesignerXmlBody(DesignerXmlBody):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["request", "response"]


@router.post("/studio/designer/xml-templates", dependencies=[Depends(require_master)], status_code=201)
def save_designer_xml_template(body: SaveDesignerXmlBody):
    try:
        name = body.name.strip()
        if not name:
            raise ValueError("Template name is required.")
        return save_catalog_template(body.kind, body.xml, template_id=body.id, name=name)
    except FileExistsError as exc:
        raise HTTPException(409, "A template with this ID already exists for this type.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/studio/designer/xml-templates", dependencies=[Depends(get_current_user)])
def designer_xml_templates():
    items = []
    sources = {}
    for definitions in definition_roots():
        base = definitions.resolve()
        for folder in ("templates", "workflows"):
            for path in sorted((base / folder).rglob("*.xml")):
                if not path.is_file() or not path.resolve().is_relative_to(base / folder):
                    continue
                relative = path.relative_to(base).with_suffix("").as_posix()
                template_file = relative.removeprefix("templates/")
                sources.setdefault(template_file, path)
    for template_file, path in sources.items():
        try:
            root = parse_template_catalog(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        wrapper = {"InputTemplates": "Input", "OutputTemplates": "Template"}.get(root.tag)
        for template in (root if wrapper else [root]):
            tag = template.tag
            if tag not in ("Input", "Template") or (wrapper and wrapper != tag):
                continue
            payloads = [item for item in template if isinstance(item.tag, str)]
            key = template.get("id")
            if key and len(payloads) == 1:
                items.append({
                    "file": template_file,
                    "id": key, "name": template.get("name") or key,
                    "kind": "request" if tag == "Input" else "response",
                    "xml": etree.tostring(payloads[0], encoding="unicode", with_tail=False, pretty_print=True).strip(),
                })
    return items


@router.post("/studio/designer/xml-preview", dependencies=[Depends(get_current_user)])
def designer_xml_preview(body: DesignerXmlBody):
    try:
        parse_sample(body.xml)
        return {"value": parse_xml_response(body.xml)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _check_designer_size(value: Any) -> None:
    pending = [(value, 0)]
    count = 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > 20_000 or depth > 60:
            raise ValueError("The workflow is too large or deeply nested for the visual designer.")
        if isinstance(node, dict):
            pending.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            pending.extend((child, depth + 1) for child in node)


@router.post("/studio/designer/parse", dependencies=[Depends(get_current_user)])
def parse_designer_workflow(body: ConfirmWorkflowBody):
    try:
        flow = yaml.safe_load(body.yaml)
        if not isinstance(flow, dict) or not isinstance(flow.get("steps"), list) or not isinstance(flow.get("inputs"), list):
            raise ValueError("The designer requires a workflow with steps and inputs lists.")
        if any(not isinstance(item, dict) for item in [*flow["steps"], *flow["inputs"]]):
            raise ValueError("Workflow steps and inputs must be mappings.")
        _check_designer_size(flow)
        return {"workflow": jsonable_encoder(flow), "actions": sorted(ACTIONS), "stepTypes": sorted(SUPPORTED_STEP_TYPES)}
    except (yaml.YAMLError, ValueError, TypeError, RecursionError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/studio/designer/validate", dependencies=[Depends(get_current_user)])
def validate_designer_workflow(body: DesignerWorkflowBody):
    flow = body.workflow
    try:
        _check_designer_size(flow)
        for key in ("id", "version"):
            if not isinstance(flow.get(key), str) or not flow[key].strip():
                raise ValueError(f"Workflow {key} is required.")
        if len(flow["id"]) > 100 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", flow["id"]):
            raise ValueError("Workflow ID must be lowercase kebab-case and at most 100 characters.")
        if any(not isinstance(step.get("id"), str) or not step["id"].strip() for step in flow.get("steps", [])):
            raise ValueError("Each step requires an ID.")
        validate_flow(flow)
        for step in flow["steps"]:
            if step["type"] == "api" and not step.get("action"):
                request = (step.get("xml_templates") or {}).get("request") or {}
                if not (request.get("file") or request.get("id") or request.get("xml") or request.get("source")):
                    raise ValueError(f"API step {step['id']} requires a request XML source or template.")
        return {"yaml": yaml.safe_dump(flow, sort_keys=False, allow_unicode=True)}
    except (yaml.YAMLError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/studio/generated-flows", dependencies=[Depends(require_master)])
def confirm_draft(body: ConfirmWorkflowBody):
    try:
        flow = yaml.safe_load(body.yaml)
        if not isinstance(flow, dict):
            raise ValueError("Workflow YAML must contain a mapping.")
        validate_flow(flow)
        content = body.yaml
        if isinstance(flow["id"], str) and re.fullmatch(r"workflow-[0-9a-f]{1,8}", flow["id"]):
            name = flow.get("name")
            flow["id"] = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:100].rstrip("-") if isinstance(name, str) else ""
            flow["id"] = flow["id"] or "new-workflow"
            content = yaml.safe_dump(flow, sort_keys=False, allow_unicode=True)
        content = externalize_workflow_xml(content, flow)
        path = save_generated_workflow(flow["id"], content)
    except FileExistsError as exc:
        raise HTTPException(409, "A workflow already uses that ID. Modify the ID and try again.") from exc
    except (yaml.YAMLError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"saved": True, "id": flow["id"], "path": path, "yaml": content}
