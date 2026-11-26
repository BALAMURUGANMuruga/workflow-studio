# Classify a prompt to help route it between workflow and document handling.
"""Train a local nearest-neighbor classifier on labeled prompt examples."""

from collections import Counter
from functools import lru_cache
from math import sqrt
from pathlib import Path
import re

# Reserve a label for document questions so the caller can hand them to the document assistant.
DOCUMENT_INTENT = "@documents"
DOCUMENTS = Path(__file__).parent / "document_assistant" / "documents"


# Convert text into a sparse unit-length vector of word counts and character trigrams.
def _features(text: str) -> dict[str, float]:
    # Case-fold the input and extract runs of ASCII letters.
    words = re.findall(r"[a-z]+", text.casefold())
    # Prefix whole-word features so they are distinct from character features.
    counts = Counter(f"word:{word}" for word in words)
    for word in words:
        # Mark word boundaries so beginning and ending trigrams can be distinguished.
        bounded = f"^{word}$"
        counts.update(bounded[index:index + 3] for index in range(len(bounded) - 2))
    # Compute Euclidean length. Use one for empty text to avoid division by zero.
    norm = sqrt(sum(count * count for count in counts.values())) or 1
    return {feature: count / norm for feature, count in counts.items()}


# Reuse computed example vectors for recently seen immutable example tuples.
@lru_cache(maxsize=4)
def _train(examples: tuple[tuple[str, str], ...]):
    return tuple((label, _features(prompt)) for label, prompt in examples)


# Read local Markdown headings once per process and reuse the synthetic document examples.
@lru_cache(maxsize=1)
def _document_examples() -> tuple[tuple[str, str], ...]:
    headings = [heading for source in sorted(DOCUMENTS.rglob("*.md"))
                for heading in re.findall(r"^##\s+(?:\d+\.\s+)?(.+)$",
                                          source.read_text(encoding="utf-8"), re.MULTILINE)]
    # Create three phrasing variants per heading and give each the document label.
    return tuple((DOCUMENT_INTENT, prompt) for heading in headings
                 for prompt in (heading, f"What is {heading}?", f"Explain {heading}"))


def classify_prompt(message: str, catalog: list[dict]) -> str | None:
    """Return a label only when the strongest example has enough support."""
    # Combine the catalog's valid command examples and phrases with the corresponding workflow IDs.
    workflow_examples = tuple(
        (workflow["id"], example)
        for workflow in catalog
        for example in (*workflow.get("examples", []), *workflow.get("executionCommands", []))
        if isinstance(example, str) and example.strip()
    )
    # Vectorize the labeled examples and combine workflow and document candidates.
    samples = _train(workflow_examples + _document_examples())
    query = _features(message)
    scores: dict[str, float] = {}
    for label, sample in samples:
        # Compute cosine similarity using the dot product of normalized sparse vectors.
        similarity = sum(value * sample.get(feature, 0.0) for feature, value in query.items())
        # Keep only the strongest example for each label.
        scores[label] = max(scores.get(label, 0.0), similarity)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if ranked:
        label, score = ranked[0]
        # Compare the best scoring label with the next distinct label.
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        # Require a minimum score and a margin over the runner-up before returning a label.
        if score >= 0.70 and score - runner_up >= 0.08:
            return label
    # Signal that the caller should fall back to workflow retrieval.
    return None
