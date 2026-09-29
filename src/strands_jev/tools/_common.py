"""Shared plumbing for the tools: endpoint resolution, input tolerance, result shape.

Every tool returns ``{"status", "content": [{"json": ...}, {"text": one line}]}``. Inputs are
tolerated when the intent is unambiguous (a JSON string where a list was meant, one item per
line) and refused before anything is spent when it is not (a threshold outside 0..1, a
boolean where a number was meant). Every error names the fix.

Which endpoint answers, in order:

1. ``invocation_state["jev"]``: per call, so one agent can serve several keys or a fake.
2. ``configure(jev)``: once, at startup.
3. ``Jev()``: the key from ``TYPESAFE_API_KEY`` or ``~/.typesafe``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

from strands.types.tools import ToolContext
from typesafe_sdk import Choice, ChoiceAnswer, Noul, NoulAnswer, NoulCriteria, Score, ScoreAnswer

from ..client import BudgetExceeded, Jev, JevEndpoint
from ..questions import (
    DEFAULT_MAX_STATE_CHARS,
    MAX_CHOICE_OPTIONS,
    MAX_CONCURRENCY,
    MAX_ITEMS_PER_BATCH,
    MAX_QUESTIONS_PER_REQUEST,
    MAX_SCORE_LEVELS,
    MIN_SCORE_LEVELS,
)

JEV_STATE_KEY = "jev"
"""Key in ``invocation_state`` under which a caller hands the tools an endpoint."""

_DEFAULT: JevEndpoint | None = None


def configure(jev: JevEndpoint | None) -> None:
    """Set the endpoint used when a call carries none. ``None`` clears it."""
    global _DEFAULT
    _DEFAULT = jev


def resolve(tool_context: ToolContext | None) -> JevEndpoint:
    """Find the endpoint for this call. See the module docstring for the order.

    Raises:
        TypeError: ``invocation_state["jev"]`` has no ``ask``.
        RuntimeError: No endpoint configured and no key on the machine.
    """
    global _DEFAULT
    if tool_context is not None:
        supplied = (tool_context.invocation_state or {}).get(JEV_STATE_KEY)
        if supplied is not None:
            if not callable(getattr(supplied, "ask", None)):
                raise TypeError(
                    f"invocation_state[{JEV_STATE_KEY!r}] must be a Jev or anything with an async ask method, "
                    f"got {type(supplied).__name__}"
                )
            return supplied  # type: ignore[no-any-return]
    if _DEFAULT is None:
        _DEFAULT = Jev()
    return _DEFAULT


# ---------------------------------------------------------------------------- results


def ok(payload: Mapping[str, Any], summary: str) -> dict[str, Any]:
    """A successful result: JSON to branch on, one line to read."""
    return {"status": "success", "content": [{"json": dict(payload)}, {"text": summary}]}


def error(text: str) -> dict[str, Any]:
    """A failed result. The text names the fix."""
    return {"status": "error", "content": [{"text": text}]}


def endpoint_error(exc: Exception) -> dict[str, Any]:
    """Turn a client failure into a result the agent can act on."""
    if isinstance(exc, BudgetExceeded):
        return error(f"Request refused before sending: {exc}")
    text = str(exc)
    if isinstance(exc, RuntimeError) and "API key" in text:
        return error(
            f"Jev is not configured: {exc} Or call strands_jev.configure(Jev(...)), "
            "or pass one in invocation_state['jev']."
        )
    return error(f"Jev did not answer ({type(exc).__name__}: {exc}). Decide without it or try once more.")


# ----------------------------------------------------------------------------- inputs


def truncate(text: str, limit: int) -> str:
    """Cut ``text`` to ``limit`` characters with a visible marker the model reads too."""
    if limit <= 0 or len(text) <= limit:
        return text
    marker = f" [truncated {len(text) - limit} characters]"
    keep = max(0, limit - len(marker))
    return text[:keep] + marker


def render_state(state: Any, context: str | None = None, max_chars: int = DEFAULT_MAX_STATE_CHARS) -> Any:
    """Shape what the model reads: a string stays a string, anything else stays JSON.

    ``context`` is folded in under its own key so the caller can hand over the user's
    request or a policy once, next to the thing being judged.
    """
    if context:
        state = {"context": context, "subject": state}
    if isinstance(state, str):
        return truncate(state, max_chars)
    rendered = json.dumps(state, default=str, ensure_ascii=False)
    if max_chars > 0 and len(rendered) > max_chars:
        return truncate(rendered, max_chars)
    return state


def as_list(value: Any, what: str, *, ceiling: int = MAX_ITEMS_PER_BATCH) -> list[Any]:
    """Read a list the caller may have sent in a less convenient shape.

    A JSON string holding a list is decoded; a multi-line string becomes one item per
    non-empty line; any other string is a single item.

    Raises:
        ValueError: Nothing usable, or more than ``ceiling`` items.
    """
    items: list[Any]
    if isinstance(value, str):
        text = value.strip()
        decoded: Any = None
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except ValueError:
                decoded = None
        if isinstance(decoded, list):
            items = decoded
        elif "\n" in text:
            items = [line.strip() for line in text.splitlines() if line.strip()]
        else:
            items = [text] if text else []
    elif isinstance(value, (list, tuple)):
        items = list(value)
    elif value is None:
        items = []
    else:
        items = [value]
    if not items:
        raise ValueError(f"{what} is empty; supply at least one")
    if len(items) > ceiling:
        raise ValueError(f"{what} has {len(items)} items, over the ceiling of {ceiling}; send it in batches")
    return items


def as_mapping(value: Any, what: str, prefix: str | None) -> dict[str, Any]:
    """Read named entries: a mapping, a list of strings, or a JSON string of either.

    A list is named ``prefix1..N`` with the text as the description; with ``prefix=None``
    each string is its own name and description (options: the label is the meaning).

    Raises:
        ValueError: Nothing usable, JSON that does not parse, or an empty name.
    """
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                value = json.loads(text)
            except ValueError as exc:
                raise ValueError(f"{what} looks like JSON but does not parse: {exc}") from exc
    result: dict[str, Any]
    if isinstance(value, Mapping):
        result = {str(key): description for key, description in value.items()}
    else:
        listed = as_list(value, what)
        if prefix is None:
            result = {str(item): str(item) for item in listed}
        else:
            result = {f"{prefix}{index}": item for index, item in enumerate(listed, start=1)}
    if not result:
        raise ValueError(f"{what} is empty; supply at least one")
    for key in result:
        if not key.strip():
            raise ValueError(f"{what} has an empty name")
    return result


def fraction(value: Any, name: str, default: float) -> float:
    """A number in 0..1, or the default when omitted. Refused, never clamped.

    Raises:
        ValueError: A boolean, not a number, or outside 0..1.
    """
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number between 0 and 1, got a boolean; write {name}=0.5")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number between 0 and 1, got {value!r}") from exc
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1, got {number}")
    return number


def whole(value: Any, name: str, default: int, low: int, high: int) -> int:
    """A whole number in ``low..high``, or the default when omitted. Refused, never clamped."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a whole number, got a boolean")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a whole number, got {value!r}") from exc
    if not low <= number <= high:
        raise ValueError(f"{name} must be between {low} and {high}, got {number}")
    return number


def preview(item: Any, limit: int = 120) -> str:
    """A short handle on an item for a result table."""
    text = item if isinstance(item, str) else json.dumps(item, default=str, ensure_ascii=False)
    return truncate(text, limit)


# --------------------------------------------------------------------------- questions

QUESTION_TYPES = {"noul", "choice", "score"}


def build_question(spec: Any, name: str) -> Noul | Choice | Score:
    """Turn a caller's question spec into an SDK question.

    Accepts an SDK question as-is, or a dict with ``type`` (``noul``, ``choice``, ``score``),
    ``instructions`` (string or structured) and ``criteria`` (Noul: optional ``{"true": ...,
    "false": ...}``; Choice: option map or list; Score: ordered level list). A plain string is
    a Noul whose instructions are the string.

    Raises:
        ValueError: Missing type, bad criteria shape, or over a documented limit.
    """
    if isinstance(spec, (Noul, Choice, Score)):
        return spec
    if isinstance(spec, str):
        return Noul(instructions=spec)
    if not isinstance(spec, Mapping):
        raise ValueError(f"question {name!r} must be a string, an SDK question or a dict, got {type(spec).__name__}")
    kind = str(spec.get("type", "")).lower()
    instructions = spec.get("instructions", spec.get("question"))
    criteria = spec.get("criteria", spec.get("options", spec.get("levels")))
    if kind not in QUESTION_TYPES:
        raise ValueError(f"question {name!r} needs type noul, choice or score, got {spec.get('type')!r}")
    if kind == "noul":
        if criteria is None:
            return Noul(instructions=instructions)
        if not isinstance(criteria, Mapping) or not set(criteria) <= {"true", "false"}:
            raise ValueError(f"question {name!r}: noul criteria must be a dict with only true and false keys")
        noul_criteria: NoulCriteria = {}
        if "true" in criteria:
            noul_criteria["true"] = criteria["true"]
        if "false" in criteria:
            noul_criteria["false"] = criteria["false"]
        return Noul(instructions=instructions, criteria=noul_criteria)
    if kind == "choice":
        if isinstance(criteria, Sequence) and not isinstance(criteria, str):
            criteria = {str(option): None for option in criteria}
        if not isinstance(criteria, Mapping) or len(criteria) < 2:
            raise ValueError(f"question {name!r}: choice needs at least two options as a dict or a list")
        if len(criteria) > MAX_CHOICE_OPTIONS:
            raise ValueError(f"question {name!r}: {len(criteria)} options, over the limit of {MAX_CHOICE_OPTIONS}")
        return Choice(instructions=instructions, criteria=dict(criteria))
    if not isinstance(criteria, Sequence) or isinstance(criteria, str):
        raise ValueError(f"question {name!r}: score needs an ordered list of level descriptions")
    if not MIN_SCORE_LEVELS <= len(criteria) <= MAX_SCORE_LEVELS:
        raise ValueError(
            f"question {name!r}: {len(criteria)} levels, needs between {MIN_SCORE_LEVELS} and {MAX_SCORE_LEVELS}"
        )
    return Score(instructions=instructions, criteria=list(criteria))


def build_questions(specs: Any) -> dict[str, Noul | Choice | Score]:
    """A named question map from a dict, a list (named q1..N) or a JSON string of either.

    Raises:
        ValueError: Nothing usable, or more than ``MAX_QUESTIONS_PER_REQUEST``.
    """
    if isinstance(specs, str):
        text = specs.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                specs = json.loads(text)
            except ValueError as exc:
                raise ValueError(f"questions looks like JSON but does not parse: {exc}") from exc
        else:
            specs = [text]
    named: dict[str, Any]
    if isinstance(specs, Mapping):
        named = dict(specs)
    else:
        named = {f"q{index}": spec for index, spec in enumerate(as_list(specs, "questions"), start=1)}
    if not named:
        raise ValueError("questions is empty; supply at least one")
    if len(named) > MAX_QUESTIONS_PER_REQUEST:
        raise ValueError(
            f"{len(named)} questions in one request, over the ceiling of {MAX_QUESTIONS_PER_REQUEST}; split them"
        )
    return {str(name): build_question(spec, str(name)) for name, spec in named.items()}


def answer_to_dict(answer: Any) -> dict[str, Any]:
    """A JSON-ready view of any SDK answer, rounded for reading."""
    if isinstance(answer, NoulAnswer):
        return {"type": "noul", "noul": round(answer.noul, 4)}
    if isinstance(answer, ChoiceAnswer):
        return {
            "type": "choice",
            "choice": answer.choice,
            "confidence": round(answer.confidence, 4),
            "probabilities": {key: round(value, 4) for key, value in answer.probabilities.items()},
        }
    if isinstance(answer, ScoreAnswer):
        return {
            "type": "score",
            "score": round(answer.score, 4),
            "confidence": round(answer.confidence, 4),
            "legend": {int(key): value for key, value in answer.legend.items()},
            "probabilities": {int(key): round(value, 4) for key, value in answer.probabilities.items()},
        }
    if hasattr(answer, "model_dump"):
        return dict(answer.model_dump())
    return {"value": answer}


def expect(answers: Mapping[str, Any], key: str, kind: type) -> Any:
    """The answer under ``key``, checked against the type the question implies."""
    answer = answers.get(key)
    if not isinstance(answer, kind):
        raise ValueError(f"expected a {kind.__name__} for {key!r}, got {type(answer).__name__}")
    return answer


async def ask_each(
    jev: JevEndpoint,
    states: Sequence[Any],
    questions: Mapping[str, Any],
    concurrency: int = MAX_CONCURRENCY,
) -> list[Mapping[str, Any] | Exception]:
    """One request per state, at most ``concurrency`` in flight. Errors are kept per item."""
    semaphore = asyncio.Semaphore(concurrency)

    async def one(state: Any) -> Mapping[str, Any] | Exception:
        async with semaphore:
            try:
                return await jev.ask(state, questions)
            except Exception as exc:  # noqa: BLE001 - reported per item
                return exc

    return list(await asyncio.gather(*(one(state) for state in states)))
