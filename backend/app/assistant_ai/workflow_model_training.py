# Build workflow training examples and train local model components using PyTorch.
"""Build training data from workflow metadata and train the local token tagger."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import torch
from torch.nn import functional as F

from .workflow_token_tagger import (
    MAX_TOKENS,
    PAD_TOKEN,
    UNKNOWN_TOKEN,
    TinyWorkflowTransformer,
    TrainedWorkflowModel,
    _model_text,
    _tokenize,
)

# Process up to 32 synthetic examples in each gradient update.
BATCH_SIZE = 32


# Generate prompt and token-label pairs from workflow definitions. O means the token lies outside a field value.
def _training_examples(
    catalog: list[dict[str, Any]],
) -> tuple[list[tuple[str, list[str]]], list[str]]:
    examples: list[tuple[str, list[str]]] = []
    # Build a stable set of output labels from the catalog input names.
    field_names = sorted(
        {
            field["name"]
            for workflow in catalog
            for field in workflow.get("inputs", [])
            if isinstance(field.get("name"), str)
        }
    )
    for workflow in catalog:
        phrases = [
            phrase
            for phrase in workflow.get("examples", [])
            if isinstance(phrase, str) and phrase.strip()
        ]
        # Use a workflow display name or ID when no example prompts are configured.
        if not phrases:
            phrases = [workflow.get("name") or workflow["id"]]

        for phrase in phrases:
            # Add an example with no supplied field values.
            examples.append((_model_text(workflow, phrase)[0], []))
            for field_index, field in enumerate(workflow.get("inputs", [])):
                name = field.get("name")
                if not isinstance(name, str):
                    continue
                # Use the field key and display label as alternative hints without duplicates.
                hints = list(dict.fromkeys((name, str(field.get("label") or name))))
                for sample_index in range(3):
                    # Make artificial values so training can teach the context around an identifier.
                    value = f"SYN{field_index}{sample_index}X"
                    for hint in hints:
                        message = f"{phrase} {hint}: {value}"
                        text, request_offset = _model_text(workflow, message)
                        # Translate the value position in the message to the corresponding contextual model input.
                        value_start = request_offset + message.rfind(value)
                        value_end = value_start + len(value)
                        # Tag only tokens fully contained in the synthetic value span.
                        labels = [
                            name
                            if start >= value_start and end <= value_end
                            else "O"
                            for _, start, end in _tokenize(text)
                        ]
                        examples.append((text, labels))

        fields = [
            field
            for field in workflow.get("inputs", [])
            if isinstance(field.get("name"), str)
        ]
        for first_index, first_field in enumerate(fields):
            for second_index, second_field in enumerate(fields):
                # Generate two-field examples using distinct fields.
                if first_index == second_index:
                    continue
                first_name = first_field["name"]
                second_name = second_field["name"]
                first_value = f"SYN{first_index}0X"
                second_value = f"SYN{second_index}1X"
                first_hint = str(first_field.get("label") or first_name)
                second_hint = str(second_field.get("label") or second_name)
                message = (
                    f"{workflow.get('name', workflow['id'])} "
                    f"{first_hint}: {first_value} {second_hint}: {second_value}"
                )
                text, request_offset = _model_text(workflow, message)
                first_start = request_offset + message.find(first_value)
                second_start = request_offset + message.find(second_value)
                labels = []
                for _, start, end in _tokenize(text):
                    if start >= first_start and end <= first_start + len(first_value):
                        labels.append(first_name)
                    elif start >= second_start and end <= second_start + len(second_value):
                        labels.append(second_name)
                    else:
                        labels.append("O")
                examples.append((text, labels))
    # Return the training rows and the output label order.
    return examples, ["O", *field_names]


# Convert contextual prompt tokens and field labels to integer sequences for PyTorch.
def _encoded_examples(
    examples: list[tuple[str, list[str]]],
    labels: list[str],
    vocabulary: dict[str, int],
) -> list[tuple[list[int], list[int]]]:
    label_ids = {name: index for index, name in enumerate(labels)}
    encoded: list[tuple[list[int], list[int]]] = []
    for text, text_labels in examples:
        # Retain the last tokens, where the current request is appended.
        tokens = _tokenize(text)[-MAX_TOKENS:]
        # Treat an example without label annotations as all outside-field tokens.
        if len(text_labels) < len(_tokenize(text)):
            text_labels = ["O"] * len(_tokenize(text))
        token_labels = text_labels[-MAX_TOKENS:]
        # Mask synthetic value tokens as unknown so the model can learn from surrounding hints.
        token_ids = [
            UNKNOWN_TOKEN if label != "O" else vocabulary.get(token, UNKNOWN_TOKEN)
            for (token, _, _), label in zip(tokens, token_labels)
        ]
        target_ids = [label_ids.get(label, 0) for label in token_labels]
        encoded.append((token_ids, target_ids))
    return encoded


# Take workflow metadata, a checkpoint path, and an epoch count. Return a trained token tagger.
def train_model(
    catalog: list[dict[str, Any]],
    model_path: Path,
    epochs: int,
) -> TrainedWorkflowModel:
    if not catalog:
        raise ValueError("Cannot train the local model without workflow definitions")
    if epochs < 1:
        raise ValueError("Training epochs must be at least one")

    # Use a fixed PyTorch seed to repeat initialization across comparable runs.
    torch.manual_seed(7)
    # Cap PyTorch CPU parallelism for this local trainer.
    torch.set_num_threads(min(torch.get_num_threads(), 4))
    examples, labels = _training_examples(catalog)
    # Reserve IDs for padding and unseen tokens before collecting training vocabulary.
    vocabulary = {"<pad>": PAD_TOKEN, "<unknown>": UNKNOWN_TOKEN}
    for text, _ in examples:
        for token, _, _ in _tokenize(text):
            if token not in vocabulary:
                vocabulary[token] = len(vocabulary)

    training_data = _encoded_examples(examples, labels, vocabulary)
    network = TinyWorkflowTransformer(len(vocabulary), len(labels))
    # Use AdamW to update the Transformer weights from gradient estimates.
    optimizer = torch.optim.AdamW(network.parameters(), lr=0.003)
    randomizer = random.Random(7)
    class_weights = torch.ones(len(labels))
    # Reduce the loss weight of O because most training tokens are outside a value.
    class_weights[0] = 0.2

    for _ in range(epochs):
        # Shuffle training rows before constructing each epoch's batches.
        randomizer.shuffle(training_data)
        network.train()
        for batch_start in range(0, len(training_data), BATCH_SIZE):
            batch = training_data[batch_start : batch_start + BATCH_SIZE]
            # Pad each batch to its longest example.
            sequence_length = max(len(token_ids) for token_ids, _ in batch)
            input_batch = torch.full(
                (len(batch), sequence_length),
                PAD_TOKEN,
                dtype=torch.long,
            )
            # Mark padded target positions with the cross-entropy ignore index.
            target_batch = torch.full(
                (len(batch), sequence_length),
                -100,
                dtype=torch.long,
            )
            for row, (token_ids, target_ids) in enumerate(batch):
                input_batch[row, : len(token_ids)] = torch.tensor(token_ids)
                target_batch[row, : len(target_ids)] = torch.tensor(target_ids)

            # Clear the previous batch's gradients before computing new ones.
            optimizer.zero_grad(set_to_none=True)
            # Predict one score per label for every token in the batch.
            logits = network(input_batch)
            # Flatten token positions and compute weighted cross-entropy, ignoring padding.
            loss = F.cross_entropy(
                logits.reshape(-1, len(labels)),
                target_batch.reshape(-1),
                weight=class_weights,
                ignore_index=-100,
            )
            # Backpropagate the loss to compute gradients for each parameter.
            loss.backward()
            # Limit gradient magnitude before updating the weights.
            torch.nn.utils.clip_grad_norm_(network.parameters(), max_norm=1.0)
            # Apply the optimizer update for this batch.
            optimizer.step()

    model_path.parent.mkdir(parents=True, exist_ok=True)
    # Persist the model parameters together with the vocabulary and label order needed by inference.
    torch.save(
        {
            "state_dict": network.state_dict(),
            "vocabulary": vocabulary,
            "labels": labels,
        },
        model_path,
    )
    # Switch off training-specific behavior before returning the model.
    network.eval()
    return TrainedWorkflowModel(network, vocabulary, labels)
