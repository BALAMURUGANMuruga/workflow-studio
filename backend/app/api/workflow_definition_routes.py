# Serve workflow and UI definitions to studio clients.
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth.authentication_routes import require_master
from ..runtime.workflow_definition_repository import list_definitions, load_flow, load_ui, save_definition
from ..runtime.workflow_validation import validate_flow, validate_ui

router = APIRouter(prefix="/api")


class DefinitionBody(BaseModel):
    yaml: str=Field(min_length=1,max_length=250000)


@router.get("/definitions")
def definitions(): return list_definitions()


@router.get("/ui/{ui_id}")
def get_ui(ui_id:str):
    try:return load_ui(ui_id)
    except FileNotFoundError:raise HTTPException(404,"UI definition not found")
    except Exception as e:raise HTTPException(400,str(e))
@router.get("/flows/{flow_id}")
def get_flow(flow_id:str):
    try:return load_flow(flow_id)
    except FileNotFoundError:raise HTTPException(404,"Flow definition not found")
    except Exception as e:raise HTTPException(400,str(e))
@router.post("/ui")
def create_ui(body:DefinitionBody, user=Depends(require_master)):
    try:
        d=yaml.safe_load(body.yaml);validate_ui(d)
        save_definition("ui",d["id"],body.yaml,True);return {"saved":True,"id":d["id"]}
    except Exception as e:raise HTTPException(400,str(e))
@router.post("/flows")
def create_flow(body:DefinitionBody, user=Depends(require_master)):
    try:
        d=yaml.safe_load(body.yaml);validate_flow(d)
        save_definition("flow",d["id"],body.yaml,True);return {"saved":True,"id":d["id"]}
    except Exception as e:raise HTTPException(400,str(e))
@router.put("/ui/{ui_id}")
def update_ui(ui_id:str,body:DefinitionBody, user=Depends(require_master)):
    try:
        d=yaml.safe_load(body.yaml);validate_ui(d);save_definition("ui",ui_id,body.yaml);return {"saved":True}
    except Exception as e:raise HTTPException(400,str(e))
@router.put("/flows/{flow_id}")
def update_flow(flow_id:str,body:DefinitionBody, user=Depends(require_master)):
    try:
        d=yaml.safe_load(body.yaml);validate_flow(d);save_definition("flow",flow_id,body.yaml);return {"saved":True}
    except Exception as e:raise HTTPException(400,str(e))
