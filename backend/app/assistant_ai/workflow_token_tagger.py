# Identify tokens that represent workflow input values.
"""Small workflow-specific Transformer architecture and inference."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch import Tensor, nn

# Reserve zero for padding and use one for tokens absent from the vocabulary.
PAD_TOKEN = 0
UNKNOWN_TOKEN = 1
# Bound the input sequence length and the supported position embedding indices.
MAX_TOKENS = 128
MODEL_DIM = 64
ATTENTION_HEADS = 4
LAYERS = 1


# Keep the network, vocabulary, and label order together as one fitted model.
@dataclass
class TrainedWorkflowModel:
    network: nn.Module
    vocabulary: dict[str, int]
    labels: list[str]


# Use a Transformer encoder to assign a field label to each input token.
class TinyWorkflowTransformer(nn.Module):
    def __init__(self, vocabulary_size: int, label_count: int) -> None:
        super().__init__()
        # Map vocabulary IDs to learned vectors and treat the padding ID specially.
        self.token_embedding = nn.Embedding(
            vocabulary_size,
            MODEL_DIM,
            padding_idx=PAD_TOKEN,
        )
        # Add a learned position vector to distinguish identical tokens at different offsets.
        self.position_embedding = nn.Embedding(MAX_TOKENS, MODEL_DIM)
        # Configure multi-head attention with GELU and batch-first tensor layout.
        layer = nn.TransformerEncoderLayer(
            d_model=MODEL_DIM,
            nhead=ATTENTION_HEADS,
            dim_feedforward=MODEL_DIM * 2,
            batch_first=True,
            activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(
            layer,
            num_layers=LAYERS,
            enable_nested_tensor=False,
        )
        # Project each contextual token vector to one score per output label.
        self.output = nn.Linear(MODEL_DIM, label_count)

    # Input shape: batch by token position. Output shape: batch by token position by label.
    def forward(self, token_ids: Tensor) -> Tensor:
        sequence_length = token_ids.shape[1]
        # Build position IDs on the same device as the token tensor.
        positions = torch.arange(sequence_length, device=token_ids.device)
        embedded = self.token_embedding(token_ids) + self.position_embedding(positions)
        # Flag padded positions so the encoder can exclude them during attention.
        padding_mask = token_ids.eq(PAD_TOKEN)
        return self.output(
            self.encoder(embedded, src_key_padding_mask=padding_mask)
        )


# Return normalized tokens and character offsets into the original text.
def _tokenize(text: str) -> list[tuple[str, int, int]]:
    return [
        (match.group().casefold(), match.start(), match.end())
        for match in re.finditer(r"\w+|[^\w\s]", text, flags=re.UNICODE)
    ]


# Prepend workflow metadata to the request and return the offset at which the request begins.
def _model_text(workflow: dict[str, Any], message: str) -> tuple[str, int]:
    fields = " ".join(
        f"{field.get('name', '')} {field.get('label', '')} {field.get('type', '')}"
        for field in workflow.get("inputs", [])
    )
    instruction = workflow.get("prompt") or ""
    prefix = f"Workflow {workflow.get('id', '')} Instructions {instruction} Fields {fields} Request "
    return prefix + message, len(prefix)


# Read a local weights checkpoint onto CPU and reconstruct the same architecture and vocabulary.
def load_model(model_path: Path) -> TrainedWorkflowModel:
    checkpoint = torch.load(model_path, map_location="cpu", weights_only=True)
    vocabulary = checkpoint["vocabulary"]
    labels = checkpoint["labels"]
    network = TinyWorkflowTransformer(len(vocabulary), len(labels))
    network.load_state_dict(checkpoint["state_dict"])
    # Use evaluation mode for deterministic inference without training dropout.
    network.eval()
    return TrainedWorkflowModel(network, vocabulary, labels)


# Extract explicitly named order identifiers with Python regex and return their original spans.
def _labeled_order_identifiers(message: str, declared: set[str]):
    aliases = {
        "orderNo": r"order[ _-]*(?:number|no)",
        "orderHeaderKey": r"order[ _-]*header[ _-]*key",
    }
    identifier = r"[a-z0-9][a-z0-9_-]*"
    for field, alias in aliases.items():
        # Ignore an alias if the selected workflow does not accept that input.
        if field not in declared:
            continue
        value_pattern = identifier
        if field == "orderNo":
            # Allow a comma-separated identifier list for orderNo.
            value_pattern += rf"(?:\s*,\s*{identifier})*"
        for match in re.finditer(
            rf"(?<![\w-])(?:{alias})\b(?:\s*[:=#]\s*|\s+)(?P<value>{value_pattern})",
            message,
            re.IGNORECASE,
        ):
            value = match.group("value")
            if value.casefold() not in {"and", "or", "is", "for", "please", "the"}:
                yield field, value, match.span()


# Take a trained model, workflow mapping, and user message. Return extracted text by declared input name.
def extract_input_values(
    model: TrainedWorkflowModel,
    workflow: dict[str, Any],
    message: str,
) -> dict[str, str]:
    model_text, request_offset = _model_text(workflow, message)
    tokens = _tokenize(model_text)
    # Keep the end of the contextual text so the request has priority over the prefix.
    tokens = tokens[-MAX_TOKENS:]
    token_ids = [
        model.vocabulary.get(token, UNKNOWN_TOKEN)
        for token, _, _ in tokens
    ]
    # Run the forward pass without gradient tracking and take the best label at each token.
    with torch.inference_mode():
        predictions = model.network(torch.tensor([token_ids]))[0].argmax(dim=-1).tolist()

    declared = {
        field["name"]
        for field in workflow.get("inputs", [])
        if isinstance(field.get("name"), str)
    }
    # Discard background labels and labels outside the selected workflow's declared inputs.
    label_to_field = {
        index: name
        for index, name in enumerate(model.labels)
        if name != "O" and name in declared
    }
    # Collect explicit identifiers first so their text spans take precedence over model predictions.
    labeled = list(_labeled_order_identifiers(message, declared))
    positions: list[tuple[int, int, str]] = []
    for (_, start, end), label_index in zip(tokens, predictions):
        field_name = label_to_field.get(label_index)
        # An explicit identifier belongs to its named field, even if the model
        # predicts another label for tokens in the same span.
        # Accept predictions only from message tokens that do not overlap an explicit identifier.
        if field_name and start >= request_offset and not any(
            start < request_offset + right and end > request_offset + left
            for _, _, (left, right) in labeled
        ):
            positions.append((start, end, field_name))

    extracted: dict[str, str] = {}
    current_field: str | None = None
    group_start = group_end = 0
    previous_end = 0
    for start, end, field_name in positions:
        # Join nearby tokens of the same field into one input value.
        if current_field == field_name and start - previous_end <= 2:
            group_end = end
        else:
            if current_field is not None:
                # Slice the original text to preserve the user's spelling and case.
                value = model_text[group_start:group_end].strip(" \t\r\n,:;.!?")
                if value:
                    extracted[current_field] = value
            current_field = field_name
            group_start, group_end = start, end
        previous_end = end
    if current_field is not None:
        value = model_text[group_start:group_end].strip(" \t\r\n,:;.!?")
        if value:
            extracted[current_field] = value

    # Apply explicit order identifiers last so the named values win.
    extracted.update((field, value) for field, value, _ in labeled)
    return extracted
