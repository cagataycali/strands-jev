"""Shared fixtures: a scripted Jev and helpers to read tool results.

Nothing here talks to a network. The unit tests assert on what the tools do with an answer:
input tolerance, refusals, thresholds, the result shape. Whether Jev answers correctly is a
different question, asked by ``tests/live``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typesafe_sdk import ChoiceAnswer, NoulAnswer, ScoreAnswer


class FakeJev:
    """A ``JevEndpoint`` that answers from a script and records what it was asked.

    ``answers`` is a dict reused on every call, or a list consumed in order. ``responder``
    is a callable ``(state, questions) -> answers`` for tests that branch on the state.
    Any question key with no scripted answer gets a neutral answer of the right type.
    """

    def __init__(
        self,
        answers: dict[str, Any] | list[dict[str, Any]] | None = None,
        *,
        responder: Any = None,
        error: BaseException | None = None,
    ) -> None:
        self._answers = answers
        self._responder = responder
        self._error = error
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self.last_model = "jev-fake"
        self.last_latency_ms = 1.0
        self.last_input_tokens = 10

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_state(self) -> Any:
        return self.calls[-1][0]

    @property
    def last_questions(self) -> dict[str, Any]:
        return self.calls[-1][1]

    async def ask(self, state: Any, questions: Any, *, model: str | None = None) -> dict[str, Any]:
        self.calls.append((state, dict(questions)))
        if self._error is not None:
            raise self._error
        if self._responder is not None:
            scripted = dict(self._responder(state, questions))
        elif isinstance(self._answers, list):
            scripted = dict(self._answers.pop(0)) if self._answers else {}
        else:
            scripted = dict(self._answers or {})
        for key, question in questions.items():
            if key not in scripted:
                scripted[key] = neutral(question)
        return scripted


def neutral(question: Any) -> Any:
    kind = getattr(question, "type", None)
    if kind == "choice":
        options = list(question.criteria)
        share = round(1 / len(options), 4)
        return ChoiceAnswer(choice=options[0], confidence=share, probabilities={o: share for o in options})
    if kind == "score":
        levels = list(question.criteria)
        share = round(1 / len(levels), 4)
        return ScoreAnswer(
            score=(len(levels) - 1) / 2,
            confidence=share,
            legend={i: level for i, level in enumerate(levels)},
            probabilities={i: share for i in range(len(levels))},
        )
    return NoulAnswer(noul=0.5)


def noul(p: float) -> NoulAnswer:
    return NoulAnswer(noul=p)


def choice(pick: str, probabilities: dict[str, float]) -> ChoiceAnswer:
    return ChoiceAnswer(choice=pick, confidence=probabilities[pick], probabilities=probabilities)


def score(value: float, levels: list[str], probabilities: dict[int, float] | None = None) -> ScoreAnswer:
    probs = probabilities or {i: (1.0 if i == round(value) else 0.0) for i in range(len(levels))}
    return ScoreAnswer(
        score=value,
        confidence=max(probs.values()),
        legend={i: level for i, level in enumerate(levels)},
        probabilities=probs,
    )


def payload(result: dict[str, Any]) -> dict[str, Any]:
    """The JSON block of a tool result."""
    for block in result["content"]:
        if "json" in block:
            return dict(block["json"])
    raise AssertionError(f"no json block in {json.dumps(result, default=str)[:300]}")


def summary(result: dict[str, Any]) -> str:
    """The text block of a tool result."""
    for block in result["content"]:
        if "text" in block:
            return str(block["text"])
    raise AssertionError("no text block")


@pytest.fixture
def fake() -> FakeJev:
    return FakeJev()
