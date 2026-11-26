# Take a question and conversation context. Coordinate retrieval and document answer generation.
"""Serve local document answers through the studio chat response format."""

from functools import lru_cache
from pathlib import Path

from .document_retrieval import LocalRAG

PACKAGE_DIR = Path(__file__).resolve().parent


# Provide the reusable local RAG service instance.
@lru_cache(maxsize=1)
def _get_document_assistant() -> LocalRAG:
    artifacts = PACKAGE_DIR / "artifacts"
    return LocalRAG(artifacts / "model.pt", artifacts / "tokenizer.json", PACKAGE_DIR / "documents")


# Pass the question, history, and optional assistant context to RAG. Return the response for the chat UI.
def answer_document_question(question: str, history=None, *, assistant_context=None) -> dict:
    if not question.strip():
        raise ValueError("Enter a question after ‘Ask docs:’.")
    result = _get_document_assistant().ask(
        question, history=history, max_new_tokens=32, assistant_context=assistant_context,
    )
    sources = list(dict.fromkeys(hit["source"] for hit in result["sources"]))
    answer = result["answer"]
    if sources:
        answer += "\n\nSources: " + ", ".join(sources)
    return {
        "success": True,
        "kind": "explanation",
        "needsInput": False,
        "assistantMessage": answer,
        "message": answer,
        "data": None,
        "sources": sources,
        "mode": result["mode"],
    }
