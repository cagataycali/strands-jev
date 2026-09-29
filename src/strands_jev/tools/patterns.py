"""Patterns: the four recipes from docs.typesafe.ai/patterns as tools.

- ``fan_out`` ports patterns/fan-out: every question in one request, speculative ones
  included, with the premise of each speculative question stated so code keeps only the
  applicable answers.
- ``route`` ports patterns/intent-routing and folds in patterns/confidence-routing: a Choice
  over intents plus a Score for complexity in one request, a confidence floor, per-intent
  thresholds for the risky ones, and a person as the default handler.
- ``composite_score`` ports patterns/composite-scoring: atomic Score questions per
  dimension, normalised to 0..1, combined under weight profiles in code. The raw scores are
  returned so a caller can reweight without asking again.
- ``function_call`` ports cookbooks/function_calling: one Choice picks the function, a
  Choice per closed-set argument, a Noul per optional argument asking whether it was stated,
  a Noul per set member, a Noul per flag; only the chosen function's answers are read.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from strands import tool
from strands.types.tools import ToolContext
from typesafe_sdk import Choice, ChoiceAnswer, Noul, NoulAnswer, Score, ScoreAnswer

from ..questions import (
    COMPOSITE_LEVELS,
    DEFAULT_COMPLEXITY_CONFIDENCE_FLOOR,
    DEFAULT_COMPLEXITY_ESCALATE_ABOVE,
    DEFAULT_CONFIDENCE_FLOOR,
    DEFAULT_NOUL_THRESHOLD,
    FUNCTION_CHOICE,
    MAX_CHOICE_OPTIONS,
    MAX_QUESTIONS_PER_REQUEST,
    MAX_SCORE_LEVELS,
    MIN_SCORE_LEVELS,
    NO_MATCH,
    NO_MATCH_DESCRIPTION,
    ROUTE_COMPLEXITY,
    ROUTE_COMPLEXITY_LEVELS,
    ROUTE_INTENT,
)
from ._common import (
    answer_to_dict,
    as_list,
    as_mapping,
    ask_each,
    build_questions,
    endpoint_error,
    error,
    expect,
    fraction,
    ok,
    preview,
    render_state,
    resolve,
)

# ----------------------------------------------------------------------------- fan_out


def _premise_holds(premise: Mapping[str, Any], answers: Mapping[str, Any]) -> tuple[bool, str]:
    """Evaluate one premise against the answers. Returns (holds, why)."""
    key = str(premise.get("question", ""))
    answer = answers.get(key)
    if answer is None:
        return False, f"premise refers to {key!r}, which is not a question in this request"
    if "equals" in premise:
        wanted = premise["equals"]
        if isinstance(answer, ChoiceAnswer):
            return answer.choice == wanted, f"{key}={answer.choice}"
        if isinstance(answer, NoulAnswer):
            truth = answer.noul >= DEFAULT_NOUL_THRESHOLD
            return truth == bool(wanted), f"{key}={answer.noul:.2f}"
        return False, f"equals needs a choice or noul under {key!r}"
    if "at_least" in premise:
        floor = float(premise["at_least"])
        if isinstance(answer, NoulAnswer):
            return answer.noul >= floor, f"{key}={answer.noul:.2f}"
        if isinstance(answer, ScoreAnswer):
            return answer.score >= floor, f"{key}={answer.score:.2f}"
        return False, f"at_least needs a noul or score under {key!r}"
    return False, "premise needs 'equals' or 'at_least'"


@tool(context=True)
async def fan_out(
    state: str | dict[str, Any] | list[Any],
    questions: dict[str, Any] | str,
    premises: dict[str, Any] | str | None = None,
    context: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Ask every question you might need in one request, then keep only the applicable answers.

    Ports the speculative fan-out pattern (docs.typesafe.ai/patterns/fan-out). Questions are
    answered in parallel against the same state and cannot see each other, so a follow-up
    question ("how severe is the bug?") is asked up front alongside the question that decides
    whether it matters ("is this a bug report?"). A premise ties the follow-up to that
    deciding answer; answers whose premise does not hold are returned under ``skipped``
    rather than dropped, so nothing is hidden. Adding questions to one request costs tokens
    but little latency.

    Args:
        state: What Jev reads: text or a JSON object with meaningful field names.
        questions: The same map of question specs as ``jev_ask`` (type noul, choice or
            score, with instructions and criteria). A JSON string is accepted.
        premises: Which questions are speculative and when they apply. A map of question
            key to ``{"question": "<other key>", "equals": <choice or true/false>}`` or
            ``{"question": "<other key>", "at_least": <number>}`` for a noul probability or
            a score. Questions without a premise always apply. A JSON string is accepted.
        context: Optional text folded in next to the state.

    Returns:
        JSON with ``answers`` (the applicable ones, same shape as ``jev_ask``), ``skipped``
        (key to the premise that failed and the answer anyway), ``model``, ``latency_ms``,
        ``input_tokens``; plus a one-line summary.
    """
    try:
        built = build_questions(questions)
        rules = as_mapping(premises, "premises", None) if premises else {}
        for key, premise in rules.items():
            if key not in built:
                return error(f"premises names {key!r}, which is not one of the questions: {', '.join(built)}")
            if not isinstance(premise, Mapping) or "question" not in premise:
                return error(f"premise for {key!r} must be a dict with 'question' and 'equals' or 'at_least'")
            if str(premise["question"]) not in built:
                return error(f"premise for {key!r} refers to {premise['question']!r}, not a question in this request")
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    try:
        answers = await jev.ask(render_state(state, context), built)
    except Exception as exc:  # noqa: BLE001
        return endpoint_error(exc)
    applicable: dict[str, Any] = {}
    skipped: dict[str, Any] = {}
    for key in built:
        if key not in answers:
            continue
        row = answer_to_dict(answers[key])
        premise = rules.get(key)
        if premise is None:
            applicable[key] = row
            continue
        holds, why = _premise_holds(premise, answers)
        if holds:
            applicable[key] = row
        else:
            skipped[key] = {"premise": dict(premise), "because": why, "answer": row}
    payload = {
        "answers": applicable,
        "skipped": skipped,
        "model": getattr(jev, "last_model", None),
        "latency_ms": round(getattr(jev, "last_latency_ms", 0.0), 1),
        "input_tokens": getattr(jev, "last_input_tokens", 0),
    }
    text = f"{len(applicable)} applicable, {len(skipped)} skipped"
    if skipped:
        text += f" ({', '.join(skipped)})"
    return ok(payload, text)


# ------------------------------------------------------------------------------- route


@tool(context=True)
async def route(
    message: str | dict[str, Any],
    intents: dict[str, str] | list[str] | str,
    handlers: dict[str, str] | str | None = None,
    min_confidence: float = DEFAULT_CONFIDENCE_FLOOR,
    thresholds: dict[str, float] | str | None = None,
    assess_complexity: bool = True,
    complex_intents: list[str] | str | None = None,
    context: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Classify a request's intent and decide who handles it: code, a specialist, or a person.

    Ports intent routing (docs.typesafe.ai/patterns/intent-routing) with confidence-gated
    routing folded in (docs.typesafe.ai/patterns/confidence-routing). One request carries a
    Choice over your intents plus ``none_of_these`` and a 3-level complexity Score. The
    decision is gated twice: the intent's confidence must clear ``min_confidence`` (or the
    intent's own entry in ``thresholds``, for the risky ones), and for the intents named in
    ``complex_intents`` a complexity score above 1 or a complexity confidence under 0.5
    escalates to a person. The pattern applies that second gate to one intent (complaints),
    not to lookups; measured on 2026-09-29, gating every intent sent two clear lookups to a
    person because a 3-level score spread its probability. The thresholds are the pattern's
    own; tune them on your data.

    Args:
        message: The request, as text or a JSON object.
        intents: Intent name to a one-sentence description of when it applies. A list of
            names works, read by name alone. A JSON string is accepted.
        handlers: Intent name to the handler label your code dispatches on (for example
            ``"code"``, ``"product_llm"``, ``"human"``). Missing intents default to their
            own name; anything undecided or escalated routes to ``"human"``.
        min_confidence: Confidence floor for acting on the intent, 0..1.
        thresholds: Per-intent floors that override ``min_confidence`` for riskier intents,
            for example ``{"approve_transfer": 0.85}``. Values 0..1.
        assess_complexity: Also score complexity, 3 levels from "a lookup answers it" to "it
            needs a person". Set false when only the intent matters.
        complex_intents: The intents whose handler depends on complexity, for example
            ``["complaint"]``. Omitted: every intent is gated. Ignored when complexity is
            not assessed.
        context: Optional text folded in next to the message.

    Returns:
        JSON with ``intent``, ``confidence``, ``decided``, ``handler``, ``escalate`` (bool),
        ``reason``, ``probabilities``, ``runner_up``, ``complexity`` (score, confidence,
        legend) when assessed, ``threshold_used``; plus a one-line summary.
    """
    try:
        named = as_mapping(intents, "intents", None)
        if len(named) < 2:
            return error("intents needs at least two entries; routing with one intent is not a decision")
        if NO_MATCH in named:
            return error(f"{NO_MATCH!r} is reserved for the no-match outcome; rename that intent")
        if len(named) + 1 > MAX_CHOICE_OPTIONS:
            return error(f"{len(named)} intents, over the limit of {MAX_CHOICE_OPTIONS - 1}")
        floor = fraction(min_confidence, "min_confidence", DEFAULT_CONFIDENCE_FLOOR)
        per_intent = {
            str(name): fraction(value, f"thresholds[{name}]", floor)
            for name, value in (as_mapping(thresholds, "thresholds", None) if thresholds else {}).items()
        }
        unknown = sorted(set(per_intent) - set(named))
        if unknown:
            return error(f"thresholds names intents that are not listed: {', '.join(unknown)}")
        labels = {str(k): str(v) for k, v in (as_mapping(handlers, "handlers", None) if handlers else {}).items()}
        unknown = sorted(set(labels) - set(named))
        if unknown:
            return error(f"handlers names intents that are not listed: {', '.join(unknown)}")
        if isinstance(assess_complexity, str):
            assess_complexity = assess_complexity.strip().lower() not in {"false", "0", "no", ""}
        gated = set(as_list(complex_intents, "complex_intents")) if complex_intents else set(named)
        unknown = sorted(gated - set(named))
        if unknown:
            return error(f"complex_intents names intents that are not listed: {', '.join(unknown)}")
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)

    criteria: dict[str, Any] = {name: (desc if desc != name else None) for name, desc in named.items()}
    criteria[NO_MATCH] = NO_MATCH_DESCRIPTION
    questions: dict[str, Any] = {"intent": Choice(instructions=ROUTE_INTENT, criteria=criteria)}
    if assess_complexity:
        questions["complexity"] = Score(instructions=ROUTE_COMPLEXITY, criteria=ROUTE_COMPLEXITY_LEVELS)
    try:
        answers = await jev.ask(render_state(message, context), questions)
        intent: ChoiceAnswer = expect(answers, "intent", ChoiceAnswer)
        complexity: ScoreAnswer | None = expect(answers, "complexity", ScoreAnswer) if assess_complexity else None
    except Exception as exc:  # noqa: BLE001
        return endpoint_error(exc)

    threshold = per_intent.get(intent.choice, floor)
    ordered = sorted(intent.probabilities.items(), key=lambda item: item[1], reverse=True)
    runner_up = ordered[1][0] if len(ordered) > 1 else None
    decided = intent.choice != NO_MATCH and intent.confidence >= threshold
    escalate = False
    reason = "confident"
    if intent.choice == NO_MATCH:
        reason = "no listed intent applies"
    elif not decided:
        reason = f"confidence {intent.confidence:.2f} is under the {threshold:.2f} floor for {intent.choice}"
    elif complexity is not None and intent.choice in gated:
        if complexity.confidence < DEFAULT_COMPLEXITY_CONFIDENCE_FLOOR:
            escalate, reason = True, f"complexity confidence {complexity.confidence:.2f} is under 0.5"
        elif complexity.score > DEFAULT_COMPLEXITY_ESCALATE_ABOVE:
            escalate, reason = True, f"complexity {complexity.score:.2f} is above 1"
    handler = "human" if (not decided or escalate) else labels.get(intent.choice, intent.choice)
    payload: dict[str, Any] = {
        "intent": intent.choice,
        "confidence": round(intent.confidence, 4),
        "decided": decided,
        "handler": handler,
        "escalate": escalate,
        "reason": reason,
        "probabilities": {key: round(value, 4) for key, value in intent.probabilities.items()},
        "runner_up": runner_up,
        "threshold_used": threshold,
    }
    if complexity is not None:
        payload["complexity"] = answer_to_dict(complexity)
    summary = f"{intent.choice} ({intent.confidence:.2f}) -> {handler}"
    if not decided or escalate:
        summary += f": {reason}"
    return ok(payload, summary)


# --------------------------------------------------------------------- composite_score


def _dimension_questions(dimensions: Mapping[str, Any], levels: list[Any]) -> dict[str, Score]:
    built: dict[str, Score] = {}
    for name, spec in dimensions.items():
        if isinstance(spec, Mapping):
            instructions = spec.get("instructions", spec.get("question"))
            own_levels = spec.get("levels", spec.get("criteria", levels))
        else:
            instructions, own_levels = spec, levels
        if not instructions:
            raise ValueError(f"dimension {name!r} needs instructions: what is being rated")
        own = as_list(own_levels, f"levels for {name!r}")
        if not MIN_SCORE_LEVELS <= len(own) <= MAX_SCORE_LEVELS:
            raise ValueError(
                f"dimension {name!r}: {len(own)} levels, needs between {MIN_SCORE_LEVELS} and {MAX_SCORE_LEVELS}"
            )
        built[str(name)] = Score(instructions=instructions, criteria=own)
    return built


def _weight_profiles(weights: Any, dimensions: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """Read weights as one profile or several named ones. Every profile is checked, not clamped."""
    if not weights:
        equal = 1.0 / len(dimensions)
        return {"equal": {name: equal for name in dimensions}}
    raw = as_mapping(weights, "weights", None)
    profiles: dict[str, Any]
    if all(isinstance(value, Mapping) for value in raw.values()):
        profiles = dict(raw)
    else:
        profiles = {"weighted": raw}
    checked: dict[str, dict[str, float]] = {}
    for profile, table in profiles.items():
        if not isinstance(table, Mapping):
            raise ValueError(f"weights[{profile!r}] must be a map of dimension to weight")
        unknown = sorted(set(map(str, table)) - set(dimensions))
        if unknown:
            raise ValueError(f"weights[{profile!r}] names dimensions that are not listed: {', '.join(unknown)}")
        row: dict[str, float] = {}
        for name, value in table.items():
            if isinstance(value, bool):
                raise ValueError(f"weights[{profile!r}][{name!r}] must be a number, got a boolean")
            number = float(value)
            if number < 0:
                raise ValueError(f"weights[{profile!r}][{name!r}] must not be negative, got {number}")
            row[str(name)] = number
        total = sum(row.values())
        if total <= 0:
            raise ValueError(f"weights[{profile!r}] sum to 0; give at least one dimension a positive weight")
        checked[str(profile)] = {name: row.get(name, 0.0) / total for name in dimensions}
    return checked


@tool(context=True)
async def composite_score(
    dimensions: dict[str, Any] | str,
    state: str | dict[str, Any] | list[Any] | None = None,
    items: list[Any] | str | None = None,
    weights: dict[str, Any] | str | None = None,
    levels: list[str] | str | None = None,
    context: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Score one thing, or rank many, on several dimensions with weights you control in code.

    Ports composite scoring (docs.typesafe.ai/patterns/composite-scoring). Each dimension is
    an atomic Score question; every dimension is asked in one request per item. Scores are
    normalised to 0..1 by dividing by the top level index, then combined under each weight
    profile in code. The raw normalised scores are returned so you can reweight without
    asking again. The default rubric has five generic levels; describe your own levels when
    the dimension has concrete stages (the docs ask that levels describe situations).

    Args:
        dimensions: Dimension name to the rating instruction ("How deep is the Python
            experience?"), or to ``{"instructions": ..., "levels": [...]}`` for a dimension
            with its own ordered levels (2 to 10). A JSON string is accepted.
        state: The one thing to score. Give this or ``items``.
        items: Several things to score and rank, one request each (at most 500).
        weights: One profile ``{"python": 0.4, "leadership": 0.1, ...}`` or several
            ``{"senior_ic": {...}, "manager": {...}}``. Non-negative, normalised to sum to 1.
            Omitted: equal weights.
        levels: Shared ordered level descriptions for dimensions that give none.
        context: Optional text folded in next to each item, such as the job description.

    Returns:
        JSON with ``dimensions`` (name to instruction), ``profiles`` (normalised weights),
        ``results`` (per item: ``scores`` 0..1 per dimension with raw score, confidence and
        legend; ``composite`` per profile), ``ranking`` (per profile, best first, when
        ``items`` was given); plus a one-line summary.
    """
    try:
        dims = as_mapping(dimensions, "dimensions", None)
        shared = as_list(levels, "levels") if levels else list(COMPOSITE_LEVELS)
        questions = _dimension_questions(dims, shared)
        profiles = _weight_profiles(weights, dims)
        if (state is None) == (items is None):
            return error("give exactly one of state (one thing) or items (several things to rank)")
        states = as_list(items, "items") if items is not None else [state]
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)

    rendered = [render_state(one, context) for one in states]
    outcomes = await ask_each(jev, rendered, questions)
    results: list[dict[str, Any]] = []
    failures = 0
    for index, (item, outcome) in enumerate(zip(states, outcomes, strict=True)):
        if isinstance(outcome, Exception):
            failures += 1
            results.append({"index": index, "item": preview(item), "error": str(outcome)})
            continue
        scores: dict[str, Any] = {}
        composite: dict[str, float] = {}
        for name, question in questions.items():
            answer = outcome.get(name)
            if not isinstance(answer, ScoreAnswer):
                failures += 1
                break
            top = len(question.criteria) - 1
            scores[name] = {
                "normalised": round(answer.score / top, 4) if top else 0.0,
                "score": round(answer.score, 4),
                "confidence": round(answer.confidence, 4),
                "level": answer.legend.get(int(round(answer.score))),
            }
        else:
            for profile, table in profiles.items():
                composite[profile] = round(sum(table[name] * scores[name]["normalised"] for name in scores), 4)
        results.append({"index": index, "item": preview(item), "scores": scores, "composite": composite})

    ranking: dict[str, list[int]] = {}
    if items is not None:
        for profile in profiles:
            scored = [row for row in results if "composite" in row and profile in row["composite"]]
            ranking[profile] = [
                row["index"] for row in sorted(scored, key=lambda r: r["composite"][profile], reverse=True)
            ]
    payload = {
        "dimensions": {name: q.instructions for name, q in questions.items()},
        "profiles": profiles,
        "results": results,
        "ranking": ranking,
        "failures": failures,
    }
    if items is None and results and "composite" in results[0]:
        parts = ", ".join(f"{p}={v:.2f}" for p, v in results[0]["composite"].items())
        return ok(payload, f"composite {parts}")
    lead = ", ".join(f"{p}: #{order[0]}" for p, order in ranking.items() if order)
    return ok(payload, f"{len(results)} items ranked; best {lead}" + (f"; {failures} failed" if failures else ""))


# ------------------------------------------------------------------------ function_call


def _catalogue(functions: Any) -> dict[str, dict[str, Any]]:
    """Read the function catalogue and refuse what cannot be dispatched."""
    raw = as_mapping(functions, "functions", None)
    catalogue: dict[str, dict[str, Any]] = {}
    for name, spec in raw.items():
        if isinstance(spec, str):
            spec = {"description": spec}
        if not isinstance(spec, Mapping):
            raise ValueError(
                f"functions[{name!r}] must be a description string or a dict with description and arguments"
            )
        arguments: dict[str, dict[str, Any]] = {}
        for arg, arg_spec in dict(spec.get("arguments") or {}).items():
            if not isinstance(arg_spec, Mapping) or not arg_spec.get("question"):
                raise ValueError(f"functions[{name!r}].arguments[{arg!r}] needs a 'question' in plain words")
            kind = str(arg_spec.get("kind", "choice" if arg_spec.get("options") else "flag")).lower()
            options = arg_spec.get("options")
            if kind in {"choice", "set"}:
                if options is None:
                    raise ValueError(f"functions[{name!r}].arguments[{arg!r}] is a {kind} and needs 'options'")
                options = as_mapping(options, f"options for {name}.{arg}", None)
                if kind == "choice" and len(options) < 2:
                    raise ValueError(
                        f"functions[{name!r}].arguments[{arg!r}] needs at least two options; one is a flag"
                    )
                if len(options) > MAX_CHOICE_OPTIONS:
                    raise ValueError(
                        f"functions[{name!r}].arguments[{arg!r}] has {len(options)} options, limit {MAX_CHOICE_OPTIONS}"
                    )
            elif kind != "flag":
                raise ValueError(
                    f"functions[{name!r}].arguments[{arg!r}] kind must be choice, set or flag, got {kind!r}"
                )
            arguments[str(arg)] = {
                "kind": kind,
                "question": str(arg_spec["question"]),
                "stated": arg_spec.get("stated"),
                "options": options,
            }
        catalogue[str(name)] = {"description": spec.get("description"), "arguments": arguments}
    if len(catalogue) < 1:
        raise ValueError("functions is empty; supply at least one")
    return catalogue


def _function_questions(catalogue: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    choice_criteria: dict[str, Any] = {name: spec["description"] for name, spec in catalogue.items()}
    choice_criteria[NO_MATCH] = "The request does not ask for any of these functions"
    questions: dict[str, Any] = {"__tool__": Choice(instructions=FUNCTION_CHOICE, criteria=choice_criteria)}
    for name, spec in catalogue.items():
        for arg, arg_spec in spec["arguments"].items():
            key = f"{name}.{arg}"
            if arg_spec["stated"]:
                questions[f"{key}?"] = Noul(instructions=arg_spec["stated"])
            if arg_spec["kind"] == "choice":
                criteria = {opt: (desc if desc != opt else None) for opt, desc in arg_spec["options"].items()}
                questions[key] = Choice(instructions=arg_spec["question"], criteria=criteria)
            elif arg_spec["kind"] == "set":
                for member, desc in arg_spec["options"].items():
                    text = arg_spec["question"].replace("{}", member)
                    if desc and desc != member:
                        text = {"member": {member: desc}, "question": text}
                    questions[f"{key}.{member}"] = Noul(instructions=text)
            else:
                questions[key] = Noul(instructions=arg_spec["question"])
    if len(questions) > MAX_QUESTIONS_PER_REQUEST:
        raise ValueError(
            f"the catalogue needs {len(questions)} questions per request, over the ceiling of "
            f"{MAX_QUESTIONS_PER_REQUEST}; split the functions into groups and route between them first"
        )
    return questions


@tool(context=True)
async def function_call(
    request: str,
    functions: dict[str, Any] | str,
    min_confidence: float = DEFAULT_CONFIDENCE_FLOOR,
    context: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Turn a natural-language request into a function name and closed-set arguments, with confidence.

    Ports the function-calling cookbook (docs.typesafe.ai/cookbooks/function_calling). One
    request carries a Choice over the functions (plus a no-match option), and for every
    function every argument: a Choice for a single value from a fixed list, a Noul per member
    for a set argument, a Noul for a flag, and an optional "stated" Noul that decides whether
    the argument was mentioned at all (when not, it is left out so the function's default
    applies). Only the chosen function's answers are read. The call's confidence is the least
    certain judgement behind it. Free text, numbers and dates are not filled: keep them as
    defaults or ask the user. Write each question about the idea, not the parameter name.

    Args:
        request: What the user said.
        functions: Function name to ``{"description": "...", "arguments": {arg:
            {"question": "...", "options": {value: meaning, ...}, "kind": "choice" | "set" |
            "flag", "stated": "Does the user say anything about ...?"}}}``. ``kind`` defaults
            to choice when options are given, flag otherwise; ``stated`` is optional; a set
            question may hold ``{}`` where the member name goes. A bare string is a
            description with no arguments. A JSON string is accepted.
        min_confidence: Floor on the call's confidence to report ``decided``, 0..1.
        context: Optional text folded in next to the request.

    Returns:
        JSON with ``function`` (or ``none_of_these``), ``arguments`` (value per filled
        argument), ``confidence`` (the minimum), ``function_confidence``, ``decided``,
        ``per_argument`` (each judgement with its probability or confidence, and whether it
        was stated), ``probabilities`` over functions; plus a one-line summary.
    """
    try:
        catalogue = _catalogue(functions)
        questions = _function_questions(catalogue)
        floor = fraction(min_confidence, "min_confidence", DEFAULT_CONFIDENCE_FLOOR)
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    try:
        answers = await jev.ask(render_state(request, context), questions)
        picked: ChoiceAnswer = expect(answers, "__tool__", ChoiceAnswer)
    except Exception as exc:  # noqa: BLE001
        return endpoint_error(exc)

    arguments: dict[str, Any] = {}
    per_argument: dict[str, Any] = {}
    confidences = [picked.confidence]
    if picked.choice in catalogue:
        for arg, arg_spec in catalogue[picked.choice]["arguments"].items():
            key = f"{picked.choice}.{arg}"
            stated_answer = answers.get(f"{key}?")
            stated = True
            if isinstance(stated_answer, NoulAnswer):
                stated = stated_answer.noul >= DEFAULT_NOUL_THRESHOLD
                confidences.append(max(stated_answer.noul, 1 - stated_answer.noul))
            detail: dict[str, Any] = {"kind": arg_spec["kind"], "stated": stated}
            if isinstance(stated_answer, NoulAnswer):
                detail["stated_probability"] = round(stated_answer.noul, 4)
            if arg_spec["kind"] == "choice":
                answer = answers.get(key)
                if isinstance(answer, ChoiceAnswer):
                    detail.update({"value": answer.choice, "confidence": round(answer.confidence, 4)})
                    if stated:
                        arguments[arg] = answer.choice
                        confidences.append(answer.confidence)
            elif arg_spec["kind"] == "set":
                members: list[str] = []
                probabilities: dict[str, float] = {}
                for member in arg_spec["options"]:
                    answer = answers.get(f"{key}.{member}")
                    if isinstance(answer, NoulAnswer):
                        probabilities[member] = round(answer.noul, 4)
                        if answer.noul >= DEFAULT_NOUL_THRESHOLD:
                            members.append(member)
                            confidences.append(answer.noul)
                detail.update({"value": members, "probabilities": probabilities})
                if stated and members:
                    arguments[arg] = members
            else:
                answer = answers.get(key)
                if isinstance(answer, NoulAnswer):
                    on = answer.noul >= DEFAULT_NOUL_THRESHOLD
                    detail.update({"value": on, "probability": round(answer.noul, 4)})
                    if stated and on:
                        arguments[arg] = True
                        confidences.append(answer.noul)
            per_argument[arg] = detail
    confidence = min(confidences)
    decided = picked.choice != NO_MATCH and confidence >= floor
    payload = {
        "function": picked.choice,
        "arguments": arguments,
        "confidence": round(confidence, 4),
        "function_confidence": round(picked.confidence, 4),
        "decided": decided,
        "per_argument": per_argument,
        "probabilities": {key: round(value, 4) for key, value in picked.probabilities.items()},
        "questions_sent": len(questions),
        "model": getattr(jev, "last_model", None),
        "latency_ms": round(getattr(jev, "last_latency_ms", 0.0), 1),
    }
    rendered_args = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
    summary = f"{picked.choice}({rendered_args}) confidence {confidence:.2f}"
    if not decided:
        summary += " (not decided)"
    return ok(payload, summary)


PATTERN_TOOLS = [fan_out, route, composite_score, function_call]
