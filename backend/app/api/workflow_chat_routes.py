# Accept chat requests and call Python chat processing. Return workflow results or assistant messages as JSON.
from typing import Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth.authentication_routes import get_current_user
from ..runtime.chat_service import AIConfigurationError, AIProviderError, process_chat_message

router = APIRouter(prefix="/api")


class ChatTurn(BaseModel):
    # Validate each turn and its optional pending-input metadata with Pydantic.
    role: Literal["user","assistant"]
    content: str=Field(min_length=1,max_length=4000)
    needsInput: bool=False
    flow: str | None=None
    inputName: str | None=None
class ChatBody(BaseModel):
    # Limit the current prompt and the number of history entries accepted.
    message: str=Field(min_length=1,max_length=4000)
    history: list[ChatTurn]=Field(default_factory=list,max_length=12)


@router.post("/chat")
def chat(body:ChatBody, user=Depends(get_current_user)):
    # FastAPI authenticates the caller before handing the validated message to the runtime.
    try:
        history = [turn.model_dump(exclude_none=True) for turn in body.history]
        return process_chat_message(body.message, history, is_master=user.get("role") == "master")
    except AIConfigurationError as e:raise HTTPException(503,str(e))
    except AIProviderError as e:raise HTTPException(502,str(e))
    except (ValueError,FileNotFoundError,yaml.YAMLError) as e:raise HTTPException(422,str(e))
