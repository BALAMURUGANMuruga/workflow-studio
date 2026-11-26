# Accept workflow inputs and expose executor results through FastAPI.
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth.authentication_routes import get_current_user
from ..runtime.workflow_definition_repository import load_ui
from ..runtime.workflow_executor import execute_with_batch

router = APIRouter(prefix="/api")


class ExecuteBody(BaseModel):
    inputs: dict = Field(default_factory=dict)


@router.post("/execute/{ui_id}")
def execute_ui(ui_id:str,body:ExecuteBody, user=Depends(get_current_user)):
    try:
        ui=load_ui(ui_id)
        if "flow" not in ui: raise ValueError("Select a workflow to execute")
        return execute_with_batch(ui["flow"],body.inputs,can_modify_trace=user.get("role") == "master")
    except Exception as e:raise HTTPException(400,str(e))
