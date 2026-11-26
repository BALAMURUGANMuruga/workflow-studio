# Read and update workflow definition files from the studio through FastAPI.
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import yaml

from ..auth.authentication_routes import require_master
from ..runtime.workflow_definition_repository import list_files, list_packs, read_file, write_file
from ..runtime.workflow_xml_storage import externalize_workflow_xml

router = APIRouter(prefix="/api")


class FileBody(BaseModel):
    path: str=Field(min_length=1,max_length=500)
    content: str=Field(max_length=500000)
    createOnly: bool=False


def _flow_preview(path: str, content: str):
    if not path.lower().endswith((".yaml", ".yml")):
        return None
    try:
        definition = yaml.safe_load(content)
    except yaml.YAMLError:
        return None
    if not isinstance(definition, dict) or not isinstance(definition.get("id"), str):
        return None
    steps = definition.get("steps")
    if not isinstance(steps, list):
        return None
    preview = {key: value for key, value in definition.items()
               if key in {"id", "name", "description", "version"} and isinstance(value, (str, int, float))}
    preview["steps"] = []
    for step in steps:
        if not isinstance(step, dict) or not all(isinstance(step.get(key), str) for key in ("id", "type")):
            return None
        node = {key: step[key] for key in ("id", "type", "name", "action", "toolName", "gotoStep")
                if isinstance(step.get(key), str)}
        for key in ("onSuccess", "onError", "onTrue", "onFalse", "onFailure"):
            handler = step.get(key)
            target = handler.get("gotoStep") if isinstance(handler, dict) else handler
            if isinstance(target, str):
                node[key] = target
        preview["steps"].append(node)
    return preview


@router.get("/studio/files")
def studio_files():
    return list_files()

@router.get("/studio/file")
def studio_read_file(path: str):
    try:
        file = read_file(path)
        return {**file, "flow": _flow_preview(file["path"], file["content"])}
    except FileNotFoundError: raise HTTPException(404, "Definition file not found")
    except Exception as e: raise HTTPException(400, str(e))

@router.post("/studio/file")
def studio_write_file(body: FileBody, user=Depends(require_master)):
    try:
        content = body.content
        if body.path.replace("\\", "/").startswith(("workflows/", "flows/")) and _flow_preview(body.path, content):
            content = externalize_workflow_xml(content, yaml.safe_load(content))
        file = write_file(body.path, content, body.createOnly)
        return {**file, "flow": _flow_preview(body.path, content), "content": content}
    except FileExistsError: raise HTTPException(409, "File already exists")
    except Exception as e: raise HTTPException(400, str(e))

@router.get("/packs")
def packs():
    """Definition packs (.jar/.zip) found in backend/packs. Drop a new jar there and call again to reload."""
    return list_packs()
