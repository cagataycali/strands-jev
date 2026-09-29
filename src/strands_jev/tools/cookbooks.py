"""Cookbooks, first shelf: search and extraction recipes from docs.typesafe.ai/cookbooks.

- ``rerank`` ports cookbooks/rerank_typesafe: one Noul per query and candidate pair, run in
  parallel, sorted by probability. The fast-search shortlist is the caller's job.
- ``find_lines`` ports cookbooks/line_search: the document as numbered lines, a Choice over
  the line ids plus a presence Noul in one request per query.
- ``extract_value`` ports cookbooks/pre_parsed_value_extraction: the candidates are found in
  code (or supplied), the model picks one, and the result is a verbatim copy.
- ``extract_date`` ports cookbooks/date_extraction: seven Choices read the shape and parts of
  a date, code assembles a calendar date and reports the weakest part's confidence.
- ``verify_citations`` ports cookbooks/citation_check: a missing quote fails by string match,
  a present one gets a Choice (supports, contradicts, says nothing) over its context.
- ``count_matching`` is the jaggedness recipe for counting: one Noul per item, count in code.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from strands import tool
from strands.types.tools import ToolContext
from typesafe_sdk import Choice, ChoiceAnswer, Noul, NoulAnswer

from ..questions import (
    CITATION_CONFIDENCE_FLOOR,
    CITATION_CRITERIA,
    CITATION_RELATION,
    CITATION_VERDICTS,
    COUNT_MATCHING,
    DATE_ABSENT,
    DATE_CONFIDENCE_FLOOR,
    DATE_DAY,
    DATE_DAY_ANCHOR,
    DATE_MODE,
    DATE_MONTH,
    DATE_WEEK_OFFSET,
    DATE_WEEKDAY,
    DATE_YEAR,
    DATE_YEAR_WINDOW,
    DEFAULT_CONFIDENCE_FLOOR,
    DEFAULT_NOUL_THRESHOLD,
    EXTRACT_VALUE_NONE,
    EXTRACT_VALUE_NONE_DESCRIPTION,
    FIND_LINES_EXISTS,
    FIND_LINES_EXISTS_CRITERIA,
    FIND_LINES_MAX_LINES,
    FIND_LINES_WHERE,
    MAX_CHOICE_OPTIONS,
    RERANK_CRITERIA,
    RERANK_INSTRUCTIONS,
)
from ._common import (
    as_list,
    as_mapping,
    ask_each,
    endpoint_error,
    error,
    expect,
    fraction,
    ok,
    preview,
    render_state,
    resolve,
    whole,
)

# ------------------------------------------------------------------------------ rerank


@tool(context=True)
async def rerank(
    query: str,
    candidates: list[Any] | str,
    instructions: str | None = None,
    top_k: int | None = None,
    context: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Re-rank a shortlist of candidates against a query, one Noul per pair, best first.

    Ports the re-ranking cookbook (docs.typesafe.ai/cookbooks/rerank_typesafe), where BM25
    shortlists of 30 court passages were re-ranked with one question per query and candidate
    pair and top-1 accuracy went from 5% to 18% over 40 queries. Fast search is your job:
    hand over the shortlist (at most 500), not the corpus. Each pair is its own request, run
    in parallel, so the score of one candidate does not depend on the others.

    Args:
        query: What is being looked for.
        candidates: The shortlist. Strings, or JSON objects (a record with fields). A JSON
            string or one candidate per line is accepted.
        instructions: Replace the default question ("Does the candidate answer the query...")
            when the relation is specific, for example the cookbook's "could the candidate
            passage be from the cited precedent".
        top_k: Return only the best k (1..500). Omitted: all, sorted.
        context: Optional text folded in next to each pair.

    Returns:
        JSON with ``ranked`` (per candidate: ``index`` in the input, ``probability``,
        ``preview``), ``best`` (the top candidate in full), ``failures``; plus a one-line
        summary.
    """
    try:
        items = as_list(candidates, "candidates")
        k = whole(top_k, "top_k", len(items), 1, len(items)) if top_k is not None else len(items)
        question = Noul(instructions=instructions or RERANK_INSTRUCTIONS, criteria=RERANK_CRITERIA)
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    states = [render_state({"query": query, "candidate": item}, context) for item in items]
    outcomes = await ask_each(jev, states, {"match": question})
    scored: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, outcome in enumerate(outcomes):
        if isinstance(outcome, Exception):
            failures.append({"index": index, "error": str(outcome)})
            continue
        answer = outcome.get("match")
        if not isinstance(answer, NoulAnswer):
            failures.append({"index": index, "error": "no noul answer"})
            continue
        scored.append({"index": index, "probability": round(answer.noul, 4), "preview": preview(items[index])})
    scored.sort(key=lambda row: row["probability"], reverse=True)
    ranked = scored[:k]
    payload = {
        "ranked": ranked,
        "best": items[ranked[0]["index"]] if ranked else None,
        "failures": failures,
        "candidates": len(items),
    }
    if not ranked:
        return ok(payload, f"no candidate scored; {len(failures)} failed")
    text = f"best #{ranked[0]['index']} at {ranked[0]['probability']:.2f}; {len(ranked)} of {len(items)} returned"
    if failures:
        text += f"; {len(failures)} failed"
    return ok(payload, text)


# -------------------------------------------------------------------------- find_lines


def _line_id(index: int) -> str:
    return f"L{index + 1:03d}"


@tool(context=True)
async def find_lines(
    document: str | list[str],
    queries: list[str] | str,
    min_presence: float = DEFAULT_NOUL_THRESHOLD,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Find which line of a document answers each query, and whether any line does at all.

    Ports the line-by-line search cookbook (docs.typesafe.ai/cookbooks/line_search). The
    document is sent once as numbered lines (``L001| ...``); each query is one request with a
    Choice over the line ids (which line answers it) and a presence Noul (does any line). The
    Choice always ranks some line first, so the Noul is what tells a real answer from the
    nearest irrelevant line. A Choice takes at most 255 options, so a longer document is
    searched window by window and the best window's line is returned, with the presence
    probability of that window.

    Args:
        document: The text, or a list of lines. Blank lines are dropped before numbering.
        queries: One or more questions to locate. A JSON string or one per line is accepted.
        min_presence: Presence probability at or above which a query is reported ``found``.

    Returns:
        JSON with ``results`` (per query: ``found``, ``presence``, ``line_id``, ``line``,
        ``line_confidence``, ``runners_up``), ``lines`` (how many were searched); plus a
        one-line summary.
    """
    try:
        raw_lines = document if isinstance(document, list) else str(document).splitlines()
        lines = [str(line).strip() for line in raw_lines if str(line).strip()]
        if not lines:
            return error("document is empty; supply the text to search")
        asks = [str(q) for q in as_list(queries, "queries")]
        floor = fraction(min_presence, "min_presence", DEFAULT_NOUL_THRESHOLD)
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)

    windows = [
        list(range(start, min(start + FIND_LINES_MAX_LINES, len(lines))))
        for start in range(0, len(lines), FIND_LINES_MAX_LINES)
    ]
    # One request per (query, window). Every window's lines carry their global ids.
    plan: list[tuple[int, int]] = [(q, w) for q in range(len(asks)) for w in range(len(windows))]
    outcomes: list[Any] = []
    for q_index, w_index in plan:
        window = windows[w_index]
        state = "\n".join(f"{_line_id(i)}| {lines[i]}" for i in window)
        questions: dict[str, Any] = {
            "where": Choice(
                instructions=FIND_LINES_WHERE.format(query=asks[q_index]), criteria={_line_id(i): None for i in window}
            ),
            "exists": Noul(
                instructions=FIND_LINES_EXISTS.format(query=asks[q_index]), criteria=FIND_LINES_EXISTS_CRITERIA
            ),
        }
        try:
            outcomes.append(await jev.ask(state, questions))
        except Exception as exc:  # noqa: BLE001 - reported per query
            outcomes.append(exc)

    results: list[dict[str, Any]] = []
    for q_index, query in enumerate(asks):
        best: dict[str, Any] | None = None
        errors: list[str] = []
        for (pq, _), outcome in zip(plan, outcomes, strict=True):
            if pq != q_index:
                continue
            if isinstance(outcome, Exception):
                errors.append(str(outcome))
                continue
            try:
                where: ChoiceAnswer = expect(outcome, "where", ChoiceAnswer)
                exists: NoulAnswer = expect(outcome, "exists", NoulAnswer)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            candidate = {"presence": exists.noul, "where": where}
            if best is None or candidate["presence"] > best["presence"]:
                best = candidate
        if best is None:
            results.append({"query": query, "found": False, "error": "; ".join(errors) or "no answer"})
            continue
        where = best["where"]
        ordered = sorted(where.probabilities.items(), key=lambda kv: kv[1], reverse=True)
        line_index = int(where.choice[1:]) - 1
        results.append(
            {
                "query": query,
                "found": best["presence"] >= floor,
                "presence": round(best["presence"], 4),
                "line_id": where.choice,
                "line": lines[line_index],
                "line_confidence": round(where.confidence, 4),
                "runners_up": [{"line_id": lid, "probability": round(p, 4)} for lid, p in ordered[1:4]],
            }
        )
    found = sum(1 for row in results if row.get("found"))
    payload = {"results": results, "lines": len(lines), "windows": len(windows), "min_presence": floor}
    parts = [
        f"{row['line_id']} ({row['presence']:.2f})" if row.get("found") else f"not found ({row.get('presence', 0):.2f})"
        for row in results
    ]
    return ok(payload, f"{found}/{len(asks)} found: " + ", ".join(parts))


# ----------------------------------------------------------------------- extract_value

_PATTERNS: dict[str, str] = {
    "email": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "phone": r"(?<![\d-])\+?\(?\d[\d ().-]{7,}\d(?![\d-])(?<!\d{4}-\d{2}-\d{2})",
    "url": r"https?://[^\s)>\]]+",
    "money": r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|dollars|euros|pounds))",
    "date": (
        r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}"
        r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}(?:st|nd|rd|th)?,? ?\d{0,4}"
        r"|\d{1,2}(?:st|nd|rd|th)? (?:of )?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*,? ?\d{0,4})\b"
    ),
    "number": r"-?\d[\d,]*(?:\.\d+)?",
    "iban": r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b",
    "percent": r"\d+(?:\.\d+)?\s?%",
}


def find_candidates(document: str, kind: str) -> list[str]:
    """Spans of one ``kind`` found in the text, in order, deduplicated, verbatim.

    Raises:
        ValueError: Unknown kind. The message lists the kinds.
    """
    if kind not in _PATTERNS:
        raise ValueError(f"unknown candidate kind {kind!r}; one of {', '.join(sorted(_PATTERNS))}, or pass candidates")
    seen: list[str] = []
    for match in re.finditer(_PATTERNS[kind], document):
        span = match.group(0).strip().rstrip(".,;")
        if span and span not in seen:
            seen.append(span)
    return seen


@tool(context=True)
async def extract_value(
    document: str,
    question: str,
    candidates: list[str] | str | None = None,
    kind: str | None = None,
    min_confidence: float = DEFAULT_CONFIDENCE_FLOOR,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Pick the value a question asks for from spans already found in the text; never re-type it.

    Ports pre-parsed value extraction (docs.typesafe.ai/cookbooks/pre_parsed_value_extraction).
    A decision model cannot generate, so extraction is a selection: code finds every span of
    the right shape (every email address, every amount), the model picks the one that plays
    the role the question names, and the result is a verbatim copy of that span. A
    ``none_of_these`` option is always present. Check coverage: the model cannot choose a
    value the finder missed.

    Args:
        document: The text the value is in.
        question: The role, in plain words: "Which email address does the sender want the
            receipt sent to?".
        candidates: The spans to choose between, if you already have them (2 to 255).
        kind: Find the candidates in the document instead: one of email, phone, url, money,
            date, number, iban, percent. Give this or ``candidates``.
        min_confidence: Floor for ``decided``, 0..1.

    Returns:
        JSON with ``value`` (verbatim, or null when none), ``confidence``, ``decided``,
        ``candidates`` (what was offered), ``probabilities``; plus a one-line summary.
    """
    try:
        if candidates is None and kind is None:
            return error(
                "give candidates (the spans to choose between) or kind "
                "(email, phone, url, money, date, number, iban, percent)"
            )
        spans = (
            [str(s) for s in as_list(candidates, "candidates")]
            if candidates is not None
            else find_candidates(document, str(kind))
        )
        floor = fraction(min_confidence, "min_confidence", DEFAULT_CONFIDENCE_FLOOR)
        if len(spans) + 1 > MAX_CHOICE_OPTIONS:
            return error(
                f"{len(spans)} candidates, over the limit of {MAX_CHOICE_OPTIONS - 1}; "
                "narrow the finder or split the document"
            )
        if not spans:
            return ok(
                {"value": None, "confidence": 1.0, "decided": True, "candidates": [], "probabilities": {}},
                f"no {kind or 'candidate'} spans in the document",
            )
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    criteria: dict[str, Any] = {span: None for span in spans}
    criteria[EXTRACT_VALUE_NONE] = EXTRACT_VALUE_NONE_DESCRIPTION
    if len(spans) == 1:
        question_obj: Choice | Noul = Noul(
            instructions={"candidate": spans[0], "question": f"Is `candidate` the answer to: {question}"}
        )
    else:
        question_obj = Choice(instructions=question, criteria=criteria)
    try:
        answers = await jev.ask(render_state(document), {"pick": question_obj})
        answer = answers["pick"]
    except Exception as exc:  # noqa: BLE001
        return endpoint_error(exc)
    if isinstance(answer, NoulAnswer):
        picked = spans[0] if answer.noul >= DEFAULT_NOUL_THRESHOLD else None
        confidence = max(answer.noul, 1 - answer.noul)
        probabilities = {spans[0]: round(answer.noul, 4), EXTRACT_VALUE_NONE: round(1 - answer.noul, 4)}
    else:
        chosen: ChoiceAnswer = expect(answers, "pick", ChoiceAnswer)
        picked = None if chosen.choice == EXTRACT_VALUE_NONE else chosen.choice
        confidence = chosen.confidence
        probabilities = {k: round(v, 4) for k, v in chosen.probabilities.items()}
    payload = {
        "value": picked,
        "confidence": round(confidence, 4),
        "decided": confidence >= floor,
        "candidates": spans,
        "probabilities": probabilities,
    }
    text = (
        f"{picked!r} ({confidence:.2f})"
        if picked is not None
        else f"none of {len(spans)} candidates ({confidence:.2f})"
    )
    if confidence < floor:
        text += " under the floor"
    return ok(payload, text)


# ------------------------------------------------------------------------ extract_date

MONTHS = list(calendar.month_name)[1:]
WEEKDAYS = list(calendar.day_name)


def date_questions(role: str) -> dict[str, Choice]:
    """The cookbook's seven Choices for one date role. No arithmetic in any of them."""
    return {
        "mode": Choice(
            instructions=DATE_MODE.format(role=role), criteria={"absolute": None, "relative": None, "none": None}
        ),
        "month": Choice(
            instructions=DATE_MONTH.format(role=role), criteria={**{m: None for m in MONTHS}, "none": DATE_ABSENT}
        ),
        "day": Choice(
            instructions=DATE_DAY.format(role=role),
            criteria={**{str(d): None for d in range(1, 32)}, "none": DATE_ABSENT},
        ),
        "year": Choice(
            instructions=DATE_YEAR.format(role=role),
            criteria={
                **{str(y): None for y in DATE_YEAR_WINDOW},
                "out_of_range": "A year is stated for this date but is outside the listed range.",
                "none": "No year is stated for this date.",
            },
        ),
        "day_anchor": Choice(
            instructions=DATE_DAY_ANCHOR.format(role=role),
            criteria={"today": None, "tomorrow": None, "day_after": None, "weekday": None, "none": DATE_ABSENT},
        ),
        "weekday": Choice(
            instructions=DATE_WEEKDAY.format(role=role), criteria={**{w: None for w in WEEKDAYS}, "none": DATE_ABSENT}
        ),
        "week_offset": Choice(
            instructions=DATE_WEEK_OFFSET.format(role=role),
            criteria={"current": None, "next": None, "none": DATE_ABSENT},
        ),
    }


def assemble_date(parts: Mapping[str, ChoiceAnswer], today: date) -> dict[str, Any]:
    """Turn the seven answers into a date, in code. Reports the weakest confidence used."""
    mode = parts["mode"]
    used = [mode.confidence]
    if mode.choice == "none":
        return {"date": None, "mode": "none", "confidence": round(mode.confidence, 4), "used": ["mode"]}
    if mode.choice == "absolute":
        month, day, year = parts["month"], parts["day"], parts["year"]
        used += [month.confidence, day.confidence]
        if month.choice == "none" or day.choice == "none":
            return {
                "date": None,
                "mode": "absolute",
                "confidence": round(min(used), 4),
                "used": ["mode", "month", "day"],
                "problem": "month or day not stated",
            }
        month_number = MONTHS.index(month.choice) + 1
        day_number = int(day.choice)
        if year.choice == "out_of_range":
            used.append(year.confidence)
            return {
                "date": None,
                "mode": "absolute",
                "confidence": round(min(used), 4),
                "used": ["mode", "month", "day", "year"],
                "problem": "year out of range",
            }
        if year.choice == "none":
            used.append(year.confidence)
            year_number = today.year
            try:
                candidate = date(year_number, month_number, day_number)
            except ValueError:
                return {
                    "date": None,
                    "mode": "absolute",
                    "confidence": round(min(used), 4),
                    "used": ["mode", "month", "day", "year"],
                    "problem": "no such day",
                }
            if candidate < today:
                candidate = date(
                    year_number + 1,
                    month_number,
                    min(day_number, calendar.monthrange(year_number + 1, month_number)[1]),
                )
            inferred = True
        else:
            used.append(year.confidence)
            year_number = int(year.choice)
            try:
                candidate = date(year_number, month_number, day_number)
            except ValueError:
                return {
                    "date": None,
                    "mode": "absolute",
                    "confidence": round(min(used), 4),
                    "used": ["mode", "month", "day", "year"],
                    "problem": "no such day",
                }
            inferred = False
        return {
            "date": candidate.isoformat(),
            "mode": "absolute",
            "confidence": round(min(used), 4),
            "used": ["mode", "month", "day", "year"],
            "year_inferred": inferred,
        }
    anchor = parts["day_anchor"]
    used.append(anchor.confidence)
    if anchor.choice in {"today", "tomorrow", "day_after"}:
        offset = {"today": 0, "tomorrow": 1, "day_after": 2}[anchor.choice]
        return {
            "date": (today + timedelta(days=offset)).isoformat(),
            "mode": "relative",
            "confidence": round(min(used), 4),
            "used": ["mode", "day_anchor"],
        }
    if anchor.choice == "weekday":
        weekday, offset_answer = parts["weekday"], parts["week_offset"]
        used += [weekday.confidence, offset_answer.confidence]
        if weekday.choice == "none":
            return {
                "date": None,
                "mode": "relative",
                "confidence": round(min(used), 4),
                "used": ["mode", "day_anchor", "weekday"],
                "problem": "weekday not stated",
            }
        target = WEEKDAYS.index(weekday.choice)
        ahead = (target - today.weekday()) % 7
        candidate = today + timedelta(days=ahead)
        if offset_answer.choice == "next":
            start_next_week = today + timedelta(days=7 - today.weekday())
            candidate = start_next_week + timedelta(days=target)
        return {
            "date": candidate.isoformat(),
            "mode": "relative",
            "confidence": round(min(used), 4),
            "used": ["mode", "day_anchor", "weekday", "week_offset"],
        }
    return {
        "date": None,
        "mode": "relative",
        "confidence": round(min(used), 4),
        "used": ["mode", "day_anchor"],
        "problem": "relative anchor not stated",
    }


@tool(context=True)
async def extract_date(
    document: str,
    role: str,
    today: str | None = None,
    min_confidence: float = DATE_CONFIDENCE_FLOOR,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Read one date out of a document as parts, assemble it in code, and gate on confidence.

    Ports the date extraction cookbook (docs.typesafe.ai/cookbooks/date_extraction). Jev does
    not do date arithmetic, so seven Choices in one request read the shape (absolute,
    relative, none) and the parts (month, day, year; or today/tomorrow/weekday and which
    week), and code assembles the calendar date from ``today``. A year the text does not
    state is inferred as the next occurrence; a stated year outside 1990 to 2040 is flagged,
    not guessed. The confidence is the lowest among the parts used.

    Args:
        document: The text that states the date.
        role: Which date, in plain words: "the payment due date", "the day of the meeting".
        today: ISO date the relative words count from. Omitted: the machine's date.
        min_confidence: Below this the date is reported for review (``decided`` false).

    Returns:
        JSON with ``date`` (ISO or null), ``mode``, ``confidence``, ``decided``, ``parts``
        (every answer), ``problem`` when the parts do not make a date; plus a one-line summary.
    """
    try:
        anchor = date.fromisoformat(today) if today else date.today()
        floor = fraction(min_confidence, "min_confidence", DATE_CONFIDENCE_FLOOR)
        if not role.strip():
            return error("role is empty; say which date, for example 'the delivery date'")
        jev = resolve(tool_context)
    except ValueError as exc:
        return error(f"today must be an ISO date such as 2026-09-29: {exc}")
    except TypeError as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    questions = date_questions(role)
    try:
        answers = await jev.ask(render_state(document), questions)
        parts = {key: expect(answers, key, ChoiceAnswer) for key in questions}
    except Exception as exc:  # noqa: BLE001
        return endpoint_error(exc)
    assembled = assemble_date(parts, anchor)
    payload = {
        **assembled,
        "decided": assembled["confidence"] >= floor and assembled.get("problem") is None,
        "today": anchor.isoformat(),
        "parts": {key: {"choice": ans.choice, "confidence": round(ans.confidence, 4)} for key, ans in parts.items()},
    }
    text = f"{assembled['date']} ({assembled['mode']}, {assembled['confidence']:.2f})"
    if assembled.get("problem"):
        text += f": {assembled['problem']}"
    elif not payload["decided"]:
        text += " under the floor, review"
    return ok(payload, text)


# ------------------------------------------------------------------- verify_citations


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _context_of(source: str, quote: str, radius: int = 600) -> str | None:
    position = _normalise(source).find(_normalise(quote))
    if position < 0:
        return None
    # Map back roughly: find in the raw text case-insensitively; fall back to the normalised window.
    match = re.search(re.escape(quote.strip()), source, flags=re.IGNORECASE)
    if match:
        start, end = match.start(), match.end()
    else:
        start = end = position
    return source[max(0, start - radius) : min(len(source), end + radius)]


@tool(context=True)
async def verify_citations(
    citations: list[Any] | str,
    sources: dict[str, str] | str,
    min_confidence: float = CITATION_CONFIDENCE_FLOOR,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Check each claim against the source it cites: quote present, and does its context support the claim.

    Ports the citation check cookbook (docs.typesafe.ai/cookbooks/citation_check). A quote
    that is not in the source fails by string match before any model call. A quote that is
    present gets one Choice over the claim and the quote's surrounding text: supports,
    contradicts, or says nothing, mapped to verified, contradicted, unsupported. A verdict
    under the confidence floor is reported for review.

    Args:
        citations: Each ``{"claim": ..., "source": <key in sources>, "quote": ...}``. A JSON
            string is accepted. At most 500.
        sources: Source key to its full text. A JSON string is accepted.
        min_confidence: Floor for acting on a verdict, 0..1. The cookbook says start high.

    Returns:
        JSON with ``results`` (per citation: ``verdict`` of verified, contradicted,
        unsupported, missing_quote or unknown_source; ``confidence``; ``decided``;
        ``probabilities``), ``counts``; plus a one-line summary.
    """
    try:
        rows = as_list(citations, "citations")
        texts = {str(k): str(v) for k, v in as_mapping(sources, "sources", None).items()}
        floor = fraction(min_confidence, "min_confidence", CITATION_CONFIDENCE_FLOOR)
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or not all(key in row for key in ("claim", "source", "quote")):
                return error(f"citations[{index}] needs claim, source and quote")
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)

    results: list[dict[str, Any] | None] = [None] * len(rows)
    to_ask: list[int] = []
    states: list[Any] = []
    for index, row in enumerate(rows):
        source = texts.get(str(row["source"]))
        if source is None:
            results[index] = {"claim": row["claim"], "verdict": "unknown_source", "confidence": 1.0, "decided": True}
            continue
        window = _context_of(source, str(row["quote"]))
        if window is None:
            results[index] = {"claim": row["claim"], "verdict": "missing_quote", "confidence": 1.0, "decided": True}
            continue
        to_ask.append(index)
        states.append({"claim": row["claim"], "quote": row["quote"], "section": window})
    question = {"relation": Choice(instructions=CITATION_RELATION, criteria=CITATION_CRITERIA)}
    outcomes = await ask_each(jev, states, question) if states else []
    for index, outcome in zip(to_ask, outcomes, strict=True):
        if isinstance(outcome, Exception):
            results[index] = {
                "claim": rows[index]["claim"],
                "verdict": "error",
                "confidence": 0.0,
                "decided": False,
                "error": str(outcome),
            }
            continue
        relation: ChoiceAnswer = expect(outcome, "relation", ChoiceAnswer)
        results[index] = {
            "claim": rows[index]["claim"],
            "verdict": CITATION_VERDICTS[relation.choice],
            "relation": relation.choice,
            "confidence": round(relation.confidence, 4),
            "decided": relation.confidence >= floor,
            "probabilities": {k: round(v, 4) for k, v in relation.probabilities.items()},
        }
    final = [row for row in results if row is not None]
    counts: dict[str, int] = {}
    for row in final:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    review = sum(1 for row in final if not row["decided"])
    payload = {"results": final, "counts": counts, "review": review, "min_confidence": floor}
    text = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    if review:
        text += f"; {review} under the floor"
    return ok(payload, text)


# ------------------------------------------------------------------- count_matching


@tool(context=True)
async def count_matching(
    items: list[Any] | str,
    condition: str,
    threshold: float = DEFAULT_NOUL_THRESHOLD,
    context: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Count how many items satisfy a condition: one Noul per item, the counting done in code.

    The jaggedness page (docs.typesafe.ai/model-jaggedness/jev-1.13) says Jev does not count
    or do arithmetic, and to count in code with one question per item. That is all this tool
    is: each item is its own request, run in parallel, and the result is the number of
    probabilities at or above the threshold, with every probability returned.

    Args:
        items: The things to test (at most 500). A JSON string or one per line is accepted.
        condition: The property, phrased so it is true or false of one item.
        threshold: Probability at or above which an item counts, 0..1.
        context: Optional text folded in next to each item, such as a definition.

    Returns:
        JSON with ``count``, ``total``, ``matching`` (indexes), ``probabilities`` (per
        index), ``failures``; plus a one-line summary.
    """
    try:
        listed = as_list(items, "items")
        floor = fraction(threshold, "threshold", DEFAULT_NOUL_THRESHOLD)
        if not condition.strip():
            return error("condition is empty; say what should be true of an item")
        jev = resolve(tool_context)
    except (ValueError, TypeError) as exc:
        return error(str(exc))
    except RuntimeError as exc:
        return endpoint_error(exc)
    question = {"match": Noul(instructions=COUNT_MATCHING.format(condition=condition))}
    outcomes = await ask_each(jev, [render_state(item, context) for item in listed], question)
    probabilities: dict[int, float] = {}
    failures: list[int] = []
    for index, outcome in enumerate(outcomes):
        answer = None if isinstance(outcome, Exception) else outcome.get("match")
        if isinstance(answer, NoulAnswer):
            probabilities[index] = round(answer.noul, 4)
        else:
            failures.append(index)
    matching = [index for index, p in probabilities.items() if p >= floor]
    payload = {
        "count": len(matching),
        "total": len(listed),
        "matching": matching,
        "probabilities": probabilities,
        "failures": failures,
        "threshold": floor,
    }
    text = f"{len(matching)} of {len(listed)} match"
    if failures:
        text += f"; {len(failures)} failed"
    return ok(payload, text)


COOKBOOK_TOOLS = [rerank, find_lines, extract_value, extract_date, verify_citations, count_matching]
