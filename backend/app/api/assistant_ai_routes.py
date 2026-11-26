# Expose FastAPI operations for the local AI services.
import os
import secrets
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..assistant_ai.workflow_intent_service import health, select_workflow
from ..assistant_ai.document_assistant.document_service import answer_document_question

router = APIRouter(prefix="/api/local-ai", tags=["local-ai"])


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    catalog: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=12)


@router.get("/health")
def local_ai_health():
    return health()


@router.post("/select")
def local_ai_select(body: ChatBody):
    return select_workflow(body.message, body.catalog, body.history)


class DocumentQuestion(BaseModel):
    message: str = Field(min_length=1, max_length=4000, pattern=r"\S")


@router.post("/answer")
def local_ai_answer(body: DocumentQuestion, x_workflow_bridge_token: str = Header(default="")):
    expected_token = os.getenv("WORKFLOW_BRIDGE_TOKEN", "")
    if not expected_token or not secrets.compare_digest(expected_token.encode(), x_workflow_bridge_token.encode()):
        raise HTTPException(401, "Invalid workflow bridge credentials")
    answer = answer_document_question(body.message)
    return {"response": answer["assistantMessage"], "mode": answer["mode"]}
