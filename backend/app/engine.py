"""Compatibility entry point backed by the canonical YAML workflow runtime."""

# Use Any for the values inside the chat response dictionary.
from typing import Any

# Reuse the canonical chat runtime for callers that still import the legacy engine.
from .runtime.chat_service import process_chat_message


# Accept chat text and optional history, then return the chat runtime response.
# Input: message and optional legacy history. Output: the assistant result or clarification mapping.
def run_message(message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    # The legacy signature accepts history. This wrapper forwards only the message.
    return process_chat_message(message)
