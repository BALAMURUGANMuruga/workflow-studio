# Take chat text, workflow metadata, and active history. Return the selected workflow and extracted inputs or a clarification.
"""Local workflow model trained from scratch with retrieval-augmented context."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

from ..core.config import get_settings
from .workflow_token_tagger import (
    TrainedWorkflowModel,
    extract_input_values,
    load_model,
)
from .workflow_retrieval import retrieve_workflows

from .workflow_model_training import train_model
from .prompt_intent_model import DOCUMENT_INTENT, classify_prompt

_ready = False
_model: TrainedWorkflowModel | None = None
_model_signature: str | None = None
# Serialize model initialization so concurrent requests can reuse one artifact.
_model_lock = Lock()


# Represent training, loading, or inference failures for the chat runtime.
class LocalModelError(RuntimeError):
    pass


# Derive a signature from the catalog so model state can be associated with its workflow definitions.
def _catalog_signature(catalog: list[dict[str, Any]]) -> str:
    settings = get_settings()
    # Serialize catalog and training settings deterministically so changes select a different checkpoint.
    payload = "workflow-transformer-v4:" + json.dumps(
        {
            "epochs": settings.local_ai_train_epochs,
            "catalog": catalog,
        },
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    # Use the first 16 hex digits of the digest to identify the local checkpoint.
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# Resolve the local model artifact path for the catalog signature.
def _model_path(signature: str) -> Path:
    return get_settings().backend_root / ".local_ai_models" / f"{signature}.pt"


# Load or train the local model used with the supplied workflow catalog.
def _get_model(catalog: list[dict[str, Any]]) -> TrainedWorkflowModel:
    global _model, _model_signature
    # Keep model lookup, loading, and training under the same process lock.
    with _model_lock:
        signature = _catalog_signature(catalog)
        # Reuse the in-memory model when its catalog signature matches.
        if _model is not None and _model_signature == signature:
            return _model

        path = _model_path(signature)
        # Load previously trained weights when the checkpoint already exists.
        if path.is_file():
            _model = load_model(path)
        else:
            settings = get_settings()
            # Train from catalog examples only when no matching artifact is present.
            _model = train_model(catalog, path, settings.local_ai_train_epochs)
        _model_signature = signature
        return _model


# Set up the local inference service during application startup.
def initialize_local_ai() -> None:
    global _ready
    # Mark the service ready. Actual model loading and training are deferred until selection.
    _ready = True
    print("Local from-scratch workflow model is ready to train on first request")


# Release local service state during application shutdown.
def shutdown_local_ai() -> None:
    global _ready, _model, _model_signature
    _ready = False
    # Drop the in-memory model reference during shutdown.
    _model = None
    _model_signature = None


# Return status and implementation metadata for the local assistant.
def health() -> dict[str, Any]:
    return {
        "status": "ok" if _ready else "not_ready",
        "model_loaded": _model is not None,
        "engine": "pytorch-causal-transformer",
        "model": "tiny-workflow-transformer",
        "rag": "bm25-workflow-metadata",
        "training_data": "synthetic-from-workflow-yaml",
        "external_ai": False,
    }


# Use the user message, workflow metadata, and recent turns to determine the workflow and input values.
def select_workflow(
    message: str,
    catalog: list[dict[str, Any]],
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("A chat message is required")
    # Return a clarification when no workflow is available for the message.
    if not catalog:
        return {
            "flowId": None,
            "inputs": {},
            "clarification": "No AI-enabled workflows are available.",
        }

    # Find the latest assistant turn that requested a follow-up input.
    pending = next(
        (
            turn
            for turn in reversed(history or [])
            if turn.get("role") == "assistant" and turn.get("needsInput") is True
        ),
        None,
    )
    pending_flow = pending.get("flow") if pending else None
    workflows_by_id = {workflow["id"]: workflow for workflow in catalog}
    # Keep a pending workflow selected so a short answer is interpreted in its context.
    if pending_flow in workflows_by_id:
        retrieved = [workflows_by_id[pending_flow]]
    else:
        # Try the local nearest-neighbor classifier for workflow and document intent.
        intent = classify_prompt(message, catalog)
        # Return no workflow so the chat service can route to document answers.
        if intent == DOCUMENT_INTENT:
            return {"flowId": None, "inputs": {}, "clarification": None}
        # Use BM25 metadata ranking if the classifier did not return a known workflow ID.
        retrieved = [workflows_by_id[intent]] if intent in workflows_by_id else retrieve_workflows(message, catalog)
    if not retrieved:
        return {
            "flowId": None,
            "inputs": {},
            "clarification": "I couldn't match that request to an available workflow.",
        }

    # Choose the top candidate before extracting any input values.
    workflow = retrieved[0]
    try:
        model = _get_model(catalog)
        inputs: dict[str, Any] = {}
        pending_input = None
        # Replay prior turns to reconstruct values already provided.
        for turn in history or []:
            if turn.get("role") == "assistant" and turn.get("needsInput") is True:
                # Remember which declared input the assistant asked for.
                pending_input = turn.get("inputName")
            elif turn.get("role") == "user" and isinstance(turn.get("content"), str):
                if pending_input in {
                    field.get("name") for field in workflow.get("inputs", [])
                }:
                    # Use the user's answer directly when a declared field was requested.
                    inputs[pending_input] = turn["content"].strip()
                    pending_input = None
                else:
                    # Run token extraction on user turns without an explicit pending field.
                    inputs.update(
                        extract_input_values(model, workflow, turn["content"])
                    )

        if pending_input in {
            field.get("name") for field in workflow.get("inputs", [])
        }:
            inputs[pending_input] = message.strip()
        else:
            inputs.update(extract_input_values(model, workflow, message.strip()))
    # Wrap expected model failures in the service-specific exception.
    except (OSError, RuntimeError, ValueError) as exc:
        raise LocalModelError(f"Local workflow model failed: {exc}") from exc

    return {
        "flowId": workflow["id"],
        "inputs": inputs,
        "clarification": None,
    }
