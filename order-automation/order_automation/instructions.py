# Parse plain-English order scenarios and extract expected values for test assertions.
from dataclasses import dataclass
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class Check:
    field: str
    expected: str
    instruction: str


@dataclass(frozen=True)
class Scenario:
    title: str
    order_number: str
    checks: tuple[Check, ...]


def _words(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold()))


def _features(value: str) -> set[str]:
    value = f"^{value}$"
    return {value[index:index + 3] for index in range(len(value) - 2)}


class FieldModel:
    """Train a nearest-example field classifier from local labeled phrases."""

    def __init__(self, examples: dict[str, list[str]]):
        self.examples = [(name, _words(phrase), _features(_words(phrase)))
                         for name, phrases in examples.items() for phrase in phrases]

    def predict(self, phrase: str) -> str:
        normalized = _words(phrase)
        exact = {name for name, sample, _ in self.examples if sample == normalized}
        if len(exact) == 1:
            return next(iter(exact))
        if len(exact) > 1:
            raise ValueError(f"Ambiguous field {phrase!r}.")
        features = _features(normalized)
        scores: dict[str, float] = {}
        for name, _, trained in self.examples:
            score = 2 * len(features & trained) / max(1, len(features) + len(trained))
            scores[name] = max(score, scores.get(name, 0))
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if ranked and ranked[0][1] >= 0.72 and (
            len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= 0.12
        ):
            return ranked[0][0]
        raise ValueError(f"Unknown or ambiguous field {phrase!r}. Use a field from field-training.json.")


OPEN = re.compile(r"^(?:open|find|search for|look up)\s+(?:the\s+)?order\s+([\w.-]+)$", re.I)
VERIFY = re.compile(r"^(?:verify|check|confirm|assert)\s+(?:that\s+)?(?:the\s+)?(.+?)\s+(?:is|equals|should be)\s+(.+)$", re.I)


def read_scenarios(path: Path, model: FieldModel) -> list[Scenario]:
    return parse_scenarios(path.read_text(encoding="utf-8"), model, label=str(path), title=path.stem)


def parse_scenarios(text: str, model: FieldModel, *, label: str = "Scenario", title: str = "Order check") -> list[Scenario]:
    scenarios = []
    default_title = title
    order_number = ""
    checks: list[Check] = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if order_number:
                if not checks:
                    raise ValueError(f"{label}:{line_number}: {title} must include a check.")
                scenarios.append(Scenario(title, order_number, tuple(checks)))
                order_number, checks = "", []
            title = line.lstrip("#").strip() or default_title
            continue
        try:
            if match := OPEN.fullmatch(line.removesuffix(".")):
                if order_number:
                    raise ValueError("Use a new heading before opening another order.")
                order_number = match[1]
            elif match := VERIFY.fullmatch(line):
                if not order_number:
                    raise ValueError("Open an order before checking its fields.")
                expected = match[2].strip()
                if len(expected) >= 2 and expected[0] == expected[-1] and expected[0] in "\"'":
                    expected = expected[1:-1]
                else:
                    expected = expected.removesuffix(".")
                if not expected:
                    raise ValueError("Enter an expected value.")
                checks.append(Check(model.predict(match[1]), expected, line))
            else:
                raise ValueError("Expected an order lookup or a field assertion.")
        except ValueError as exc:
            raise ValueError(f"{label}:{line_number}: {exc}") from exc
    if order_number and checks:
        scenarios.append(Scenario(title, order_number, tuple(checks)))
    elif order_number:
        raise ValueError(f"{label}: {title} must include a check.")
    if not scenarios:
        raise ValueError(f"{label}: no scenarios found.")
    return scenarios


def load_model(path: Path) -> FieldModel:
    return FieldModel(json.loads(path.read_text(encoding="utf-8")))
