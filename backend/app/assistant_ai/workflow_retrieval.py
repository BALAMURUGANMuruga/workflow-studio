# Rank workflow metadata against a user query with BM25. Return candidate workflows for local selection.
"""Lightweight BM25 retrieval over workflow metadata."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


# Tokenize normalized text into ASCII letters and digits for lexical retrieval.
def _terms(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


# Combine workflow metadata and input labels into the searchable document for one workflow.
def _workflow_text(workflow: dict[str, Any]) -> str:
    parts = [
        workflow.get("id", ""),
        workflow.get("name", ""),
        workflow.get("description", ""),
        workflow.get("intent", ""),
        " ".join(workflow.get("examples", [])),
    ]
    for field in workflow.get("inputs", []):
        parts.extend(
            [
                field.get("name", ""),
                field.get("label", ""),
                field.get("help", ""),
                field.get("placeholder", ""),
            ]
        )
    return " ".join(str(part) for part in parts if part)


def retrieve_workflows(
    query: str,
    catalog: list[dict[str, Any]],
    limit: int = 1,
) -> list[dict[str, Any]]:
    # Score each distinct query term once.
    query_terms = set(_terms(query))
    # Return no matches when the request, catalog, or requested result count is empty.
    if not query_terms or not catalog or limit < 1:
        return []

    # Count metadata term occurrences separately for each catalog item.
    documents = [Counter(_terms(_workflow_text(workflow))) for workflow in catalog]
    # Measure how many tokens appear in each workflow document.
    lengths = [sum(document.values()) for document in documents]
    # Use the catalog's average document length to normalize scores across workflows.
    average_length = sum(lengths) / len(lengths)
    # Count in how many catalog documents each query term occurs.
    document_frequency = {
        term: sum(term in document for document in documents)
        for term in query_terms
    }

    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for index, (workflow, document) in enumerate(zip(catalog, documents)):
        score = 0.0
        for term in query_terms:
            frequency = document.get(term, 0)
            if not frequency:
                continue
            frequency_in_documents = document_frequency[term]
            # Give more weight to terms that occur in fewer workflow documents.
            inverse_frequency = math.log(
                1 + (len(catalog) - frequency_in_documents + 0.5)
                / (frequency_in_documents + 0.5)
            )
            # Apply BM25 term-frequency saturation and normalize by document length.
            denominator = frequency + 1.5 * (
                1 - 0.75 + 0.75 * lengths[index] / max(average_length, 1)
            )
            # Accumulate this query term's contribution to the workflow score.
            score += inverse_frequency * frequency * 2.5 / denominator
        # Keep candidates with at least one matching term.
        if score > 0:
            ranked.append((score, index, workflow))

    # Sort by descending score and preserve catalog order for ties.
    ranked.sort(key=lambda item: (-item[0], item[1]))
    # Return only the requested number of workflow mappings.
    return [workflow for _, _, workflow in ranked[:limit]]
