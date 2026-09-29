"""Cookbooks, second shelf: alignment, hierarchy, structure, guardrails, catalogues, consistency.

- ``align_entities`` ports cookbooks/knowledge_graph_entity_alignment: a 3-level Score per
  pair decides link, review or leave; companion Nouls per field say where the two disagree.
- ``classify_hierarchical`` ports cookbooks/hierarchical_classification: one Choice per level
  of a taxonomy, descending while confident, with a no-match option at every level.
- ``recover_structure`` ports cookbooks/autoformat: pass 1 stitches lines a line break tore
  apart, pass 2 classifies blocks and renders Markdown.
- ``guardrail`` ports cookbooks/guardrails: four hazard Nouls and a severity Score over an
  LLM's input or output in one request; the policy (thresholds and actions) lives in code.
- ``pick_from_catalog`` ports cookbooks/skill_suggestion: rank a whole catalogue in one
  request, re-check the top k in a second, return at most one pick or none.
- ``consistency_check`` ports cookbooks/self_consistency: ask, optionally ask again, report
  agreement, and route answers near a threshold to review.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from strands import tool
from strands.types.tools import ToolContext
from typesafe_sdk import Choice, ChoiceAnswer, Noul, NoulAnswer, Score, ScoreAnswer

from ..questions import (
    ALIGN_FIELD,
    ALIGN_LEVELS,
    ALIGN_OUTCOMES,
    ALIGN_RELATION,
    CATALOG_FITS,
    CATALOG_GATES,
    CATALOG_GATES_INVERTED,
    CATALOG_TOP_K,
    CATALOG_WHICH,
    CONSISTENCY_REPEATS_MAX,
    DEFAULT_CONFIDENCE_FLOOR,
    DEFAULT_NOUL_THRESHOLD,
    DEFAULT_UNCERTAIN_MARGIN,
    GUARD_ACTION_THRESHOLD,
    GUARD_INPUT,
    GUARD_OUTPUT,
    GUARD_REVIEW_THRESHOLD,
    GUARD_SEVERITY,
    GUARD_SEVERITY_BLOCK,
    GUARD_SEVERITY_LEVELS,
    HIERARCHY_CHILD,
    HIERARCHY_NONE_DESCRIPTION,
    MAX_CHOICE_OPTIONS,
    MAX_QUESTIONS_PER_REQUEST,
    NO_MATCH,
    STRUCTURE_CALLOUT,
    STRUCTURE_CALLOUTS,
    STRUCTURE_HEADING_MAX_CHARS,
    STRUCTURE_HLEVEL,
    STRUCTURE_HLEVELS,
    STRUCTURE_JOIN,
    STRUCTURE_JOIN_AFTER_DANGLING,
    STRUCTURE_JOIN_AFTER_TERMINAL,
    STRUCTURE_JOIN_CRITERIA,
    STRUCTURE_ORDERED_LIST_MEAN,
    STRUCTURE_STEP,
    STRUCTURE_STEP_CRITERIA,
    STRUCTURE_TYPE,
    STRUCTURE_TYPES,
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
    render_state,
    resolve,
    whole,
)

# ------------------------------------------------------------------------ align_entities


@tool(context=True)
async def align_entities(
    pairs: list[Any] | str,
    fields: list[str] | str | None = None,
    levels: list[str] | str | None = None,
    context: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Decide for each pair of records whether they are the same thing, related, or different.

    Ports knowledge-graph entity alignment (docs.typesafe.ai/cookbooks/knowledge_graph_entity_alignment).
    One request per pair carries a 3-level Score (different, closely related, the same) and a
    Noul per named field ("do the two state the same brewery?"). The three level descriptions
    are the whole decision: index 0 leaves the pair unlinked, 1 sends it to review, 2 asserts
    they are the same. Numeric fields are not asked about; compare numbers in code.

    Args:
        pairs: Each ``{"left": {...}, "right": {...}}`` (records as JSON objects or text). At
            most 500. A JSON string is accepted.
        fields: Field names to ask a same-or-not Noul about, e.g. ``["name", "brewery"]``.
        levels: Your own three level descriptions, in order, to replace the defaults.
        context: Optional text folded in next to each pair, such as what the records are.

    Returns:
        JSON with ``results`` (per pair: ``outcome`` of same, review or leave_unlinked,
        ``level``, ``score``, ``confidence``, ``fields`` with the probability that each
        agrees), ``counts``; plus a one-line summary.
    """
    try:
        rows = as_list(pairs, "pairs")
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or "left" not in row or "right" not in row:
                return error(f"pairs[{index}] needs left and right")
        names = [str(f) for f in as_list(fields, "fields")] if fields else []
        scale = [str(level) for level in as_list(levels, "levels")] if levels else list(ALIGN_LEVELS)
        if len(scale) != 3:
            return error(f"levels needs exactly three descriptions (different, related, same), got {len(scale)}")
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    questions: dict[str, Any] = {"relation": Score(instructions=ALIGN_RELATION, criteria=scale)}
    for name in names:
        questions[f"same_{name}"] = Noul(instructions=ALIGN_FIELD.format(field=name))
    states = [render_state({"left": row["left"], "right": row["right"]}, context) for row in rows]
    outcomes = await ask_each(jev, states, questions)
    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for index, outcome in enumerate(outcomes):
        if isinstance(outcome, Exception):
            results.append({"index": index, "outcome": "error", "error": str(outcome)})
            counts["error"] = counts.get("error", 0) + 1
            continue
        relation: ScoreAnswer = expect(outcome, "relation", ScoreAnswer)
        level = int(round(relation.score))
        outcome_name = ALIGN_OUTCOMES[max(0, min(2, level))]
        agreements = {}
        for name in names:
            answer = outcome.get(f"same_{name}")
            if isinstance(answer, NoulAnswer):
                agreements[name] = round(answer.noul, 4)
        results.append(
            {
                "index": index,
                "outcome": outcome_name,
                "level": level,
                "score": round(relation.score, 4),
                "confidence": round(relation.confidence, 4),
                "fields": agreements,
                "disagree": [name for name, p in agreements.items() if p < DEFAULT_NOUL_THRESHOLD],
            }
        )
        counts[outcome_name] = counts.get(outcome_name, 0) + 1
    payload = {"results": results, "counts": counts, "levels": scale}
    return ok(payload, ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


# ----------------------------------------------------------------- classify_hierarchical


def _children(node: Any) -> dict[str, Any]:
    if isinstance(node, Mapping) and isinstance(node.get("children"), Mapping):
        return dict(node["children"])
    return {}


def _description(node: Any) -> Any:
    if isinstance(node, Mapping):
        return node.get("description")
    return node


@tool(context=True)
async def classify_hierarchical(
    document: str | dict[str, Any],
    taxonomy: dict[str, Any] | str,
    min_confidence: float = DEFAULT_CONFIDENCE_FLOOR,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Classify a document down a taxonomy, one Choice per level, stopping when confidence drops.

    Ports hierarchical classification (docs.typesafe.ai/cookbooks/hierarchical_classification).
    The top level is one Choice over the root categories plus ``none_of_these``; the chosen
    category's children are the next Choice, and so on. Each level is its own request because
    the options depend on the previous answer. Descent stops at a leaf, at ``none_of_these``,
    or when a level's confidence is under the floor; the path so far is returned either way.

    Args:
        document: The text, or a JSON object.
        taxonomy: ``{"category": "description", ...}`` or, with children, ``{"category":
            {"description": "...", "children": {...}}}`` to any depth. Each level needs at
            least two options. A JSON string is accepted.
        min_confidence: Confidence floor per level, 0..1.

    Returns:
        JSON with ``path`` (categories chosen, top first), ``leaf`` (bool), ``levels`` (per
        level: ``choice``, ``confidence``, ``probabilities``, ``decided``), ``stopped_because``;
        plus a one-line summary.
    """
    try:
        tree = as_mapping(taxonomy, "taxonomy", None)
        floor = fraction(min_confidence, "min_confidence", DEFAULT_CONFIDENCE_FLOOR)
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    state = render_state(document)
    path: list[str] = []
    levels: list[dict[str, Any]] = []
    options = tree
    stopped = "leaf"
    while options:
        if len(options) < 2:
            stopped = (
                f"level under {path[-1]!r} has one option; a level needs at least two" if path else "taxonomy needs two"
            )
            break
        if len(options) + 1 > MAX_CHOICE_OPTIONS:
            return error(f"a level has {len(options)} categories, over the limit of {MAX_CHOICE_OPTIONS - 1}; split it")
        criteria: dict[str, Any] = {name: _description(node) for name, node in options.items()}
        criteria[NO_MATCH] = HIERARCHY_NONE_DESCRIPTION
        try:
            answers = await jev.ask(state, {"child": Choice(instructions=HIERARCHY_CHILD, criteria=criteria)})
            chosen: ChoiceAnswer = expect(answers, "child", ChoiceAnswer)
        except Exception as exc:  # noqa: BLE001
            return endpoint_error(exc)
        decided = chosen.choice != NO_MATCH and chosen.confidence >= floor
        levels.append(
            {
                "options": list(options),
                "choice": chosen.choice,
                "confidence": round(chosen.confidence, 4),
                "probabilities": {k: round(v, 4) for k, v in chosen.probabilities.items()},
                "decided": decided,
            }
        )
        if chosen.choice == NO_MATCH:
            stopped = "no category fits at this level"
            break
        if not decided:
            stopped = f"confidence {chosen.confidence:.2f} under the {floor:.2f} floor"
            break
        path.append(chosen.choice)
        options = _children(options[chosen.choice])
    payload = {"path": path, "leaf": stopped == "leaf" and bool(path), "levels": levels, "stopped_because": stopped}
    text = " > ".join(path) if path else "unclassified"
    if stopped != "leaf":
        text += f" ({stopped})"
    return ok(payload, text)


# -------------------------------------------------------------------- recover_structure


def _ends_terminal(text: str) -> bool:
    return re.search(r"[.!?:;\u2026][\"')\]]*$", text) is not None


def _block_id(index: int) -> str:
    return f"B{index + 1:03d}"


def _line_id(index: int) -> str:
    return f"L{index + 1:03d}"


def stitch_lines(raw_lines: list[str], joins: Mapping[int, float]) -> list[str]:
    """Merge torn lines. ``joins[i]`` is the probability line i continues line i-1."""
    blocks: list[str] = []
    for index, line in enumerate(raw_lines):
        if index and index in joins:
            bar = (
                STRUCTURE_JOIN_AFTER_TERMINAL if _ends_terminal(raw_lines[index - 1]) else STRUCTURE_JOIN_AFTER_DANGLING
            )
            if joins[index] >= bar and blocks:
                blocks[-1] = f"{blocks[-1]} {line}".strip()
                continue
        blocks.append(line)
    return blocks


def render_markdown(blocks: list[dict[str, Any]]) -> str:
    """Blocks with their classifications to Markdown, list items grouped, ordered when steps."""
    out: list[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        kind = block["type"]
        if kind == "list_item":
            group = []
            while index < len(blocks) and blocks[index]["type"] == "list_item":
                group.append(blocks[index])
                index += 1
            ordered = sum(item.get("step", 0.0) for item in group) / len(group) >= STRUCTURE_ORDERED_LIST_MEAN
            for number, item in enumerate(group, start=1):
                out.append(f"{number}. {item['text']}" if ordered else f"- {item['text']}")
            out.append("")
            continue
        text = block["text"]
        if kind == "heading":
            marks = {"title": "#", "section": "##", "subsection": "###"}.get(
                block.get("heading_level") or "section", "##"
            )
            out.append(f"{marks} {text}")
        elif kind == "quote":
            out.append(f"> {text}")
        elif kind == "code":
            out.extend(["```", text, "```"])
        elif kind == "callout":
            label = (block.get("callout") or "note").upper()
            out.append(f"> **{label}:** {text}")
        else:
            out.append(text)
        out.append("")
        index += 1
    return "\n".join(out).strip() + "\n"


@tool(context=True)
async def recover_structure(text: str, tool_context: ToolContext | None = None) -> dict[str, Any]:
    """Turn flattened text (torn lines, lost headings and lists) back into structured Markdown.

    Ports the autoformat cookbook (docs.typesafe.ai/cookbooks/autoformat). Pass 1 sends the
    numbered lines once and asks, for every adjacent pair, whether the second line picks up
    mid-sentence; a pair merges at 0.2 after a line with no closing punctuation and at 0.5
    after one that ends in punctuation. Pass 2 sends the stitched blocks once and asks each
    block's type, plus companion questions up front (heading level for short blocks, whether
    a list item is an ordered step, which kind of callout); code reads only the ones the type
    calls for. Long inputs are split into requests of at most 128 questions.

    Args:
        text: The flattened text. Blank lines are kept as hard breaks between blocks.

    Returns:
        JSON with ``markdown``, ``blocks`` (text, type, confidence, heading_level, step,
        callout), ``lines_in``, ``blocks_out``, ``requests``; plus a one-line summary.
    """
    try:
        raw_lines = [line.rstrip() for line in str(text).splitlines()]
        lines = [line.strip() for line in raw_lines]
        if not any(lines):
            return error("text is empty; supply the flattened text")
        jev = resolve(tool_context)
    except TypeError as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)

    # Pass 1: join questions for adjacent non-blank pairs, chunked to the question ceiling.
    kept = [(index, line) for index, line in enumerate(lines) if line]
    numbered = "\n".join(f"{_line_id(i)}| {line}" for i, line in kept)
    pair_indexes = [i for position, (i, _) in enumerate(kept) if position and kept[position - 1][0] == i - 1]
    joins: dict[int, float] = {}
    requests = 0
    for start in range(0, len(pair_indexes), MAX_QUESTIONS_PER_REQUEST):
        chunk = pair_indexes[start : start + MAX_QUESTIONS_PER_REQUEST]
        questions: dict[str, Any] = {
            _line_id(i): Noul(
                instructions=STRUCTURE_JOIN.format(this=_line_id(i), previous=_line_id(i - 1)),
                criteria=STRUCTURE_JOIN_CRITERIA,
            )
            for i in chunk
        }
        try:
            answers = await jev.ask(numbered, questions)
        except Exception as exc:  # noqa: BLE001
            return endpoint_error(exc)
        requests += 1
        for i in chunk:
            answer = answers.get(_line_id(i))
            joins[i] = answer.noul if isinstance(answer, NoulAnswer) else 0.0
    non_blank = [line for line in lines if line]
    # Blank lines are hard breaks: stitch inside runs only.
    blocks_text: list[str] = []
    run: list[str] = []
    run_start = 0
    for index, line in enumerate(lines + [""]):
        if line:
            if not run:
                run_start = index
            run.append(line)
            continue
        if run:
            local_joins = {k - run_start: v for k, v in joins.items() if run_start < k < run_start + len(run)}
            blocks_text.extend(stitch_lines(run, local_joins))
            run = []

    # Pass 2: classify blocks, companion questions up front, chunked.
    tagged = "\n".join(f"{_block_id(i)}| {text_}" for i, text_ in enumerate(blocks_text))
    blocks: list[dict[str, Any]] = [{"text": text_} for text_ in blocks_text]
    per_block: list[dict[str, Any]] = []
    for i, block_text in enumerate(blocks_text):
        bid = _block_id(i)
        qs: dict[str, Any] = {
            f"type_{bid}": Choice(instructions=STRUCTURE_TYPE.format(block=bid), criteria=STRUCTURE_TYPES),
            f"step_{bid}": Noul(instructions=STRUCTURE_STEP.format(block=bid), criteria=STRUCTURE_STEP_CRITERIA),
            f"callout_{bid}": Choice(instructions=STRUCTURE_CALLOUT.format(block=bid), criteria=STRUCTURE_CALLOUTS),
        }
        if len(block_text) <= STRUCTURE_HEADING_MAX_CHARS:
            qs[f"hlevel_{bid}"] = Choice(instructions=STRUCTURE_HLEVEL.format(block=bid), criteria=STRUCTURE_HLEVELS)
        per_block.append(qs)
    pending: dict[str, Any] = {}
    all_answers: dict[str, Any] = {}

    async def flush() -> dict[str, Any] | None:
        nonlocal pending, requests
        if not pending:
            return None
        try:
            got = await jev.ask(tagged, pending)
        except Exception as exc:  # noqa: BLE001
            return endpoint_error(exc)
        requests += 1
        all_answers.update(got)
        pending = {}
        return None

    for qs in per_block:
        if len(pending) + len(qs) > MAX_QUESTIONS_PER_REQUEST:
            failed = await flush()
            if failed:
                return failed
        pending.update(qs)
    failed = await flush()
    if failed:
        return failed
    for i, block in enumerate(blocks):
        bid = _block_id(i)
        kind = all_answers.get(f"type_{bid}")
        block["type"] = kind.choice if isinstance(kind, ChoiceAnswer) else "paragraph"
        block["confidence"] = round(kind.confidence, 4) if isinstance(kind, ChoiceAnswer) else 0.0
        level = all_answers.get(f"hlevel_{bid}")
        block["heading_level"] = (
            level.choice if isinstance(level, ChoiceAnswer) and block["type"] == "heading" else None
        )
        step = all_answers.get(f"step_{bid}")
        block["step"] = round(step.noul, 4) if isinstance(step, NoulAnswer) else 0.0
        callout = all_answers.get(f"callout_{bid}")
        block["callout"] = callout.choice if isinstance(callout, ChoiceAnswer) and block["type"] == "callout" else None
    markdown = render_markdown(blocks)
    kinds: dict[str, int] = {}
    for block in blocks:
        kinds[block["type"]] = kinds.get(block["type"], 0) + 1
    payload = {
        "markdown": markdown,
        "blocks": blocks,
        "lines_in": len(non_blank),
        "blocks_out": len(blocks),
        "requests": requests,
        "kinds": kinds,
    }
    return ok(
        payload,
        f"{len(non_blank)} lines -> {len(blocks)} blocks in {requests} requests: "
        + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())),
    )


# ----------------------------------------------------------------------------- guardrail


@tool(context=True)
async def guardrail(
    message: str,
    side: str = "input",
    policy: dict[str, Any] | str | None = None,
    context: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Screen an LLM's input or output for hazards with four Nouls and a severity Score, then apply a policy.

    Ports guardrails for LLMs (docs.typesafe.ai/cookbooks/guardrails). The input battery asks
    whether the message tries to override the assistant's instructions, asks for help with
    harm or a crime, asks for a diagnosis or dosage, or signals self-harm; the output battery
    asks whether a reply went ahead and did those things. A 4-level severity Score rides in
    the same request. Jev supplies the assessment; the policy is code: each hazard has an
    action threshold and a lower review threshold, and severity at or above its threshold
    turns a review into a block. The defaults here (0.7, 0.4, severity 2.0) are this
    package's, not the cookbook's; set them for your product.

    Args:
        message: The user message (``side="input"``) or the assistant reply (``side="output"``).
        side: ``input`` or ``output``.
        policy: ``{"action": 0.7, "review": 0.4, "severity_block": 2.0, "actions": {"jailbreak":
            "block", "medical_advice": "redirect", ...}}``; any key may be omitted. Per-hazard
            thresholds: ``{"thresholds": {"self_harm": {"action": 0.5, "review": 0.2}}}``.
        context: Optional text folded in next to the message, such as the system prompt's scope.

    Returns:
        JSON with ``decision`` (pass, review or the hazard's action), ``fired`` (hazards at or
        above their action threshold), ``review`` (hazards in the review band), ``hazards``
        (probability per hazard), ``severity`` (score, level, confidence); plus a one-line summary.
    """
    try:
        battery = {"input": GUARD_INPUT, "output": GUARD_OUTPUT}.get(str(side).lower())
        if battery is None:
            return error(f"side must be input or output, got {side!r}")
        rules = as_mapping(policy, "policy", None) if policy else {}
        action_floor = fraction(rules.get("action"), "policy.action", GUARD_ACTION_THRESHOLD)
        review_floor = fraction(rules.get("review"), "policy.review", GUARD_REVIEW_THRESHOLD)
        if review_floor > action_floor:
            return error(f"policy.review ({review_floor}) must not exceed policy.action ({action_floor})")
        severity_block = float(str(rules.get("severity_block", GUARD_SEVERITY_BLOCK)))
        if not 0.0 <= severity_block <= 3.0:
            return error(f"policy.severity_block must be between 0 and 3 (the four levels), got {severity_block}")
        actions = {str(k): str(v) for k, v in dict(rules.get("actions") or {}).items()}
        per_hazard = dict(rules.get("thresholds") or {})
        unknown = sorted((set(actions) | set(per_hazard)) - set(battery))
        if unknown:
            return error(
                f"policy names hazards not in the {side} battery: {', '.join(unknown)}; use {', '.join(battery)}"
            )
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    questions: dict[str, Any] = {
        name: Noul(instructions=text, criteria={"true": yes, "false": no}) for name, (text, yes, no) in battery.items()
    }
    questions["severity"] = Score(instructions=GUARD_SEVERITY, criteria=GUARD_SEVERITY_LEVELS)
    try:
        answers = await jev.ask(render_state(message, context), questions)
        severity: ScoreAnswer = expect(answers, "severity", ScoreAnswer)
    except Exception as exc:  # noqa: BLE001
        return endpoint_error(exc)
    hazards: dict[str, float] = {}
    fired: list[str] = []
    review: list[str] = []
    for name in battery:
        answer = answers.get(name)
        if not isinstance(answer, NoulAnswer):
            continue
        hazards[name] = round(answer.noul, 4)
        own = per_hazard.get(name) or {}
        act = fraction(
            own.get("action") if isinstance(own, Mapping) else None, f"thresholds.{name}.action", action_floor
        )
        rev = fraction(
            own.get("review") if isinstance(own, Mapping) else None, f"thresholds.{name}.review", review_floor
        )
        if answer.noul >= act:
            fired.append(name)
        elif answer.noul >= rev:
            review.append(name)
    if fired:
        decision = actions.get(fired[0], "block")
    elif review:
        decision = "block" if severity.score >= severity_block else "review"
    else:
        decision = "pass"
    payload = {
        "decision": decision,
        "fired": fired,
        "review": review,
        "hazards": hazards,
        "severity": answer_to_dict(severity),
        "side": side,
        "policy": {"action": action_floor, "review": review_floor, "severity_block": severity_block},
    }
    text = decision
    if fired:
        text += f": {', '.join(f'{h} {hazards[h]:.2f}' for h in fired)}"
    elif review:
        text += f": {', '.join(f'{h} {hazards[h]:.2f}' for h in review)} (severity {severity.score:.2f})"
    return ok(payload, text)


# ---------------------------------------------------------------------- pick_from_catalog


@tool(context=True)
async def pick_from_catalog(
    request: str,
    catalog: dict[str, Any] | str,
    top_k: int = CATALOG_TOP_K,
    min_confidence: float = DEFAULT_CONFIDENCE_FLOOR,
    gates: bool = True,
    context: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Pick at most one entry from a large catalogue for a request: rank everything, then re-check the top k.

    Ports skill suggestion (docs.typesafe.ai/cookbooks/skill_suggestion), where 182 agent
    skills were ranked in one Choice and the top few re-checked. Request 1: a Choice over the
    whole catalogue (short descriptions) plus three gate Nouls asking whether any entry should
    apply at all (acts on the user's resources; would follow a documented procedure; prose
    suffices, inverted). Request 2: a Choice over the top k with their full descriptions and a
    fits Noul per candidate. The pick is the request-2 choice when its confidence clears the
    floor and its fits Noul is at or above 0.5; otherwise none.

    Args:
        request: What the user asked.
        catalog: Entry name to a short description, or to ``{"description": "...", "details":
            "longer text for the re-check"}``. 2 to 255 entries; shard larger catalogues.
        top_k: How many to re-check (1..20).
        min_confidence: Floor on the re-check confidence for a pick.
        gates: Ask the three gate questions and report them; when all point away from the
            catalogue the result is none even if an entry ranks first.
        context: Optional text folded in next to the request, such as recent conversation.

    Returns:
        JSON with ``pick`` (name or null), ``confidence``, ``fits``, ``shortlist`` (top k with
        rank-1 probabilities, re-check probabilities and fits), ``gates`` (probabilities and
        whether they point to the catalogue), ``requests``; plus a one-line summary.
    """
    try:
        entries = as_mapping(catalog, "catalog", None)
        if len(entries) < 2:
            return error("catalog needs at least two entries")
        if len(entries) > MAX_CHOICE_OPTIONS:
            return error(
                f"catalog has {len(entries)} entries, over the limit of {MAX_CHOICE_OPTIONS}; shard it, pick per shard"
            )
        k = whole(top_k, "top_k", CATALOG_TOP_K, 1, 20)
        floor = fraction(min_confidence, "min_confidence", DEFAULT_CONFIDENCE_FLOOR)
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    short = {name: (_description(node) or name) for name, node in entries.items()}
    full = {
        name: (
            f"{_description(node)} {node.get('details', '')}".strip()
            if isinstance(node, Mapping)
            else _description(node)
        )
        for name, node in entries.items()
    }
    state = render_state(request, context)
    questions: dict[str, Any] = {"which": Choice(instructions=CATALOG_WHICH, criteria=short)}
    if gates:
        for key, text in CATALOG_GATES.items():
            questions[f"gate_{key}"] = Noul(instructions=text)
    try:
        first = await jev.ask(state, questions)
        ranked: ChoiceAnswer = expect(first, "which", ChoiceAnswer)
    except Exception as exc:  # noqa: BLE001
        return endpoint_error(exc)
    gate_rows: dict[str, Any] = {}
    toward = 0
    for key in CATALOG_GATES if gates else []:
        answer = first.get(f"gate_{key}")
        if isinstance(answer, NoulAnswer):
            points = (
                (answer.noul < DEFAULT_NOUL_THRESHOLD)
                if key in CATALOG_GATES_INVERTED
                else (answer.noul >= DEFAULT_NOUL_THRESHOLD)
            )
            gate_rows[key] = {"probability": round(answer.noul, 4), "points_to_catalog": points}
            toward += int(points)
    order = sorted(ranked.probabilities.items(), key=lambda kv: kv[1], reverse=True)[: min(k, len(entries))]
    names = [name for name, _ in order]
    second_questions: dict[str, Any] = (
        {"which": Choice(instructions=CATALOG_WHICH, criteria={n: full[n] for n in names})} if len(names) > 1 else {}
    )
    for name in names:
        second_questions[f"fits_{name}"] = Noul(instructions=CATALOG_FITS.format(name=name, description=full[name]))
    try:
        second = await jev.ask(state, second_questions)
    except Exception as exc:  # noqa: BLE001
        return endpoint_error(exc)
    rechecked = second.get("which") if len(names) > 1 else None
    best = rechecked.choice if isinstance(rechecked, ChoiceAnswer) else names[0]
    best_confidence = rechecked.confidence if isinstance(rechecked, ChoiceAnswer) else 1.0
    shortlist = []
    for name, p in order:
        fits = second.get(f"fits_{name}")
        shortlist.append(
            {
                "name": name,
                "rank_probability": round(p, 4),
                "recheck_probability": round(rechecked.probabilities.get(name, 0.0), 4)
                if isinstance(rechecked, ChoiceAnswer)
                else None,
                "fits": round(fits.noul, 4) if isinstance(fits, NoulAnswer) else None,
            }
        )
    fits_answer = second.get(f"fits_{best}")
    fits_best: float | None = round(fits_answer.noul, 4) if isinstance(fits_answer, NoulAnswer) else None
    gated_out = bool(gates and gate_rows and toward == 0)
    pick = (
        best
        if (best_confidence >= floor and (fits_best is None or fits_best >= DEFAULT_NOUL_THRESHOLD) and not gated_out)
        else None
    )
    payload = {
        "pick": pick,
        "confidence": round(best_confidence, 4),
        "fits": fits_best,
        "shortlist": shortlist,
        "gates": gate_rows,
        "requests": 2,
        "candidates": len(entries),
    }
    if pick:
        text = f"{pick} ({best_confidence:.2f}, fits {fits_best if fits_best is not None else 'n/a'})"
    elif gated_out:
        text = f"none: the gates point away from the catalogue (best was {best} at {best_confidence:.2f})"
    else:
        text = f"none: best {best} at {best_confidence:.2f}, fits {fits_best}"
    return ok(payload, text)


# ------------------------------------------------------------------- consistency_check


@tool(context=True)
async def consistency_check(
    state: str | dict[str, Any] | list[Any],
    questions: dict[str, Any] | list[Any] | str,
    repeats: int = 1,
    threshold: float = DEFAULT_NOUL_THRESHOLD,
    margin: float = DEFAULT_UNCERTAIN_MARGIN,
    min_confidence: float = DEFAULT_CONFIDENCE_FLOOR,
    context: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Ask, optionally ask again, and route anything near a threshold to review instead of deciding.

    Ports the self-consistency cookbooks (docs.typesafe.ai/cookbooks/self_consistency_nouls
    and self_consistency_choices), which repeated the same questions and compared agreement
    with sampled LLM answers. Here the raw values are always returned; a noul within
    ``margin`` of ``threshold`` or a choice or score under ``min_confidence`` is listed under
    ``review``. With ``repeats`` above 1 the same request is sent again and the agreement of
    the decided value across repeats is reported per question.

    Args:
        state: What Jev reads.
        questions: The same map of question specs as ``jev_ask``.
        repeats: How many times to ask (1..5). Each repeat is a full request.
        threshold: Noul cut for yes, 0..1.
        margin: Half-width of the band around ``threshold`` reported as uncertain.
        min_confidence: Floor for a choice or score to count as decided.
        context: Optional text folded in next to the state.

    Returns:
        JSON with ``answers`` (per question: ``value``, ``decided``, ``agreement`` across
        repeats, ``raw`` per repeat), ``review`` (question keys), ``repeats``; plus a summary.
    """
    try:
        built = build_questions(questions)
        n = whole(repeats, "repeats", 1, 1, CONSISTENCY_REPEATS_MAX)
        cut = fraction(threshold, "threshold", DEFAULT_NOUL_THRESHOLD)
        band = fraction(margin, "margin", DEFAULT_UNCERTAIN_MARGIN)
        floor = fraction(min_confidence, "min_confidence", DEFAULT_CONFIDENCE_FLOOR)
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    rendered = render_state(state, context)
    outcomes = await ask_each(jev, [rendered] * n, built)
    runs = [o for o in outcomes if not isinstance(o, Exception)]
    if not runs:
        return endpoint_error(next(o for o in outcomes if isinstance(o, Exception)))
    answers: dict[str, Any] = {}
    review: list[str] = []
    for key in built:
        raws = [run[key] for run in runs if key in run]
        if not raws:
            continue
        values: list[Any] = []
        decided_flags: list[bool] = []
        for answer in raws:
            if isinstance(answer, NoulAnswer):
                values.append(answer.noul >= cut)
                decided_flags.append(abs(answer.noul - cut) >= band)
            elif isinstance(answer, ChoiceAnswer):
                values.append(answer.choice)
                decided_flags.append(answer.confidence >= floor)
            elif isinstance(answer, ScoreAnswer):
                values.append(int(round(answer.score)))
                decided_flags.append(answer.confidence >= floor)
        first = raws[0]
        majority = max(set(values), key=values.count)
        agreement = values.count(majority) / len(values)
        decided = all(decided_flags) and agreement == 1.0
        answers[key] = {
            "value": majority,
            "decided": decided,
            "agreement": round(agreement, 4),
            "raw": [answer_to_dict(a) for a in raws],
            "type": answer_to_dict(first)["type"],
        }
        if not decided:
            review.append(key)
    payload = {
        "answers": answers,
        "review": review,
        "repeats": len(runs),
        "threshold": cut,
        "margin": band,
        "min_confidence": floor,
    }
    text = f"{len(answers) - len(review)}/{len(answers)} decided"
    if review:
        text += f"; review: {', '.join(review)}"
    if n > 1:
        text += f" ({len(runs)} repeats)"
    return ok(payload, text)


COOKBOOK_TOOLS_2 = [
    align_entities,
    classify_hierarchical,
    recover_structure,
    guardrail,
    pick_from_catalog,
    consistency_check,
]
