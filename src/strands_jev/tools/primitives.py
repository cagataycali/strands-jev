"""Primitives: the raw API as three tools.

``jev_ask`` is the whole of ``POST /v1/systemone`` (docs.typesafe.ai/api): one state, a map of
mixed typed questions, one request, typed answers back. Every other tool in this package is a
specialisation of it with the questions written for you. ``jev_models`` is ``GET /v1/models``.
``jev_usage`` reads the tally the client keeps.
"""

from __future__ import annotations

from typing import Any

from strands import tool
from strands.types.tools import ToolContext

from ..client import Jev
from ._common import answer_to_dict, build_questions, endpoint_error, error, ok, render_state, resolve


@tool(context=True)
async def jev_ask(
    state: str | dict[str, Any] | list[Any],
    questions: dict[str, Any] | list[Any] | str,
    context: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Ask Jev any mix of typed questions about one piece of state, in one request.

    This is the raw System One call. Use it when no specialised tool fits: write the
    questions yourself. Three question types (docs.typesafe.ai/primitives): ``noul`` is a
    yes/no question that returns the probability of yes; ``choice`` picks one option from a
    set you define (up to 255) and returns the option, its confidence and every option's
    probability; ``score`` rates the state on an ordered scale of 2 to 10 levels you
    describe and returns a probability-weighted position with index 0 the first level. All
    questions are answered against the same state in parallel and cannot see each other,
    so ask everything at once, including speculative questions whose premise may not hold.
    Jev reads literally: it does not count, do arithmetic, compare dates or follow
    indirection, and it cannot generate text.

    Args:
        state: What Jev reads. Text, or a JSON object whose field names carry meaning
            (``{"ticket": ..., "policy": ...}``). Questions can point into it with
            backticked paths such as ```ticket.messages[0].text```.
        questions: A map of your own keys to question specs. A spec is
            ``{"type": "noul", "instructions": "...", "criteria": {"true": ..., "false": ...}}``
            (criteria optional), ``{"type": "choice", "instructions": "...", "criteria":
            {"option": "when it applies", ...}}`` or ``{"type": "score", "instructions":
            "...", "criteria": ["level 0", "level 1", ...]}``. Instructions and criteria may be
            structured objects instead of strings. A plain string is a noul. A list is named
            q1..qN. A JSON string of either shape is accepted. Keys are not shown to the model.
        context: Optional text folded in next to the state, such as the user's request.

    Returns:
        JSON with ``answers`` (per key: ``noul``, or ``choice`` + ``confidence`` +
        ``probabilities``, or ``score`` + ``confidence`` + ``legend`` + ``probabilities``),
        ``model`` (the versioned id that answered), ``latency_ms`` and ``input_tokens``;
        plus a one-line summary.
    """
    try:
        built = build_questions(questions)
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    try:
        answers = await jev.ask(render_state(state, context), built)
    except Exception as exc:  # noqa: BLE001 - surfaced as a result
        return endpoint_error(exc)
    rows = {key: answer_to_dict(answers[key]) for key in built if key in answers}
    payload = {
        "answers": rows,
        "model": getattr(jev, "last_model", None),
        "latency_ms": round(getattr(jev, "last_latency_ms", 0.0), 1),
        "input_tokens": getattr(jev, "last_input_tokens", 0),
    }
    parts = []
    for key, row in rows.items():
        if row["type"] == "noul":
            parts.append(f"{key}={row['noul']:.2f}")
        elif row["type"] == "choice":
            parts.append(f"{key}={row['choice']} ({row['confidence']:.2f})")
        else:
            parts.append(f"{key}={row['score']:.2f} ({row['confidence']:.2f})")
    return ok(payload, f"{len(rows)} answers: " + ", ".join(parts))


@tool(context=True)
async def jev_models(tool_context: ToolContext | None = None) -> dict[str, Any]:
    """List the model ids the Jev endpoint serves, with their aliases.

    Ports ``GET /v1/models`` (docs.typesafe.ai/models). ``jev-latest`` is an alias that
    follows new releases; pin a versioned id such as ``jev-1.13.0`` when thresholds were
    tuned against it.

    Returns:
        JSON with ``models`` (the raw rows from the endpoint) and a one-line summary.
    """
    try:
        jev = resolve(tool_context)
    except (TypeError, RuntimeError) as exc:
        return endpoint_error(exc)
    lister = getattr(jev, "models", None)
    if not callable(lister):
        return error(
            "This endpoint does not list models; only a Jev client does. Pass a Jev in invocation_state['jev']."
        )
    try:
        rows = await lister()
    except Exception as exc:  # noqa: BLE001
        return endpoint_error(exc)
    ids = [str(row.get("name", row.get("id", row))) for row in rows]
    return ok({"models": rows}, f"{len(rows)} models: {', '.join(ids)}")


@tool(context=True)
async def jev_usage(reset: bool = False, tool_context: ToolContext | None = None) -> dict[str, Any]:
    """Report what the Jev calls in this process have cost so far.

    The API reports input and output tokens; cost is computed at $0.042 per million input
    tokens (docs.typesafe.ai/models, 2026-09-29), output tokens being free.

    Args:
        reset: Zero the counters after reading them.

    Returns:
        JSON with ``calls``, ``questions``, ``input_tokens``, ``output_tokens``, ``cost_usd``,
        ``latency_ms_mean``, ``latency_ms_total`` and ``last_model``; plus a one-line summary.
    """
    try:
        jev = resolve(tool_context)
    except (TypeError, RuntimeError) as exc:
        return endpoint_error(exc)
    if not isinstance(jev, Jev) and not hasattr(jev, "usage"):
        return error("This endpoint keeps no usage tally; only a Jev client does.")
    usage = jev.usage
    payload = usage.as_dict() if hasattr(usage, "as_dict") else dict(usage)
    if reset and hasattr(jev, "reset_usage"):
        jev.reset_usage()
    return ok(payload, str(usage))


PRIMITIVE_TOOLS = [jev_ask, jev_models, jev_usage]
