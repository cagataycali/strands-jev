"""Cookbook tools live, first shelf, against lexical baselines."""

from __future__ import annotations

import re
from typing import Any

import pytest

from strands_jev import Jev, count_matching, extract_date, extract_value, find_lines, rerank, verify_citations
from tests.conftest import payload
from tests.live.conftest import Board, Ctx, card_from

pytestmark = pytest.mark.live


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / (len(ta | tb) or 1)


# ------------------------------------------------------------------------------ rerank

PASSAGES = [
    "Refund requests made within 14 days of purchase are honoured in full; after that a credit note is issued.",
    "The refund policy page was last updated in March and lists the customer service opening hours.",
    "Accounts are suspended after three failed payment attempts and reinstated once the balance is settled.",
    "Suspended accounts keep their data for 90 days, after which it is deleted.",
    "Our API rate limit is 1,200 requests per minute per key; exceeding it returns HTTP 429.",
    "Rate limits are documented on the API page, together with the changelog and support contacts.",
    "Two-factor authentication can be enabled from the security tab using an authenticator app.",
    "The security tab also shows recent logins and lets you download an account activity report.",
]
# (query, index of the passage that answers it). Each has a lexical decoy nearby.
RERANK_CASES = [
    ("Can I get my money back a week after buying?", 0),
    ("Why was my account locked after my card kept getting declined?", 2),
    ("What happens if I call the API too often?", 4),
    ("How do I turn on a one-time code at login?", 6),
    ("How long before a locked account's information is erased?", 3),
    ("Where can I see who signed in to my account recently?", 7),
]


async def test_rerank_beats_lexical_overlap(jev: Jev, board: Board) -> None:
    rows: list[dict[str, Any]] = []
    for query, truth in RERANK_CASES:
        result = await rerank(query=query, candidates=PASSAGES, tool_context=Ctx(jev))
        assert result["status"] == "success", result
        body = payload(result)
        model_top = body["ranked"][0]["index"]
        base_top = max(range(len(PASSAGES)), key=lambda i: _overlap(query, PASSAGES[i]))
        rows.append(
            {
                "query": query,
                "truth": truth,
                "model": model_top,
                "baseline": base_top,
                "model_ok": model_top == truth,
                "baseline_ok": base_top == truth,
                "top3": body["ranked"][:3],
            }
        )
    card = card_from(
        jev, "rerank", rows, notes="top-1 over 8 passages with lexical decoys; baseline is token Jaccard overlap"
    )
    board.add(card)
    card.check()


# --------------------------------------------------------------------------- find_lines

TERMS = """1. Definitions
"Service" means the hosted software described on the order form.
"Customer Data" means data uploaded by you or on your behalf.
2. Accounts
You must keep your password confidential.
We may close accounts that stay unpaid for sixty days.
3. Fees
Fees are invoiced monthly in arrears.
Late payments accrue interest at 1.5% per month.
Prices may change with thirty days' written notice.
4. Data
We process Customer Data only on your instructions.
Backups are retained for thirty-five days.
You can export your data at any time in CSV or JSON.
5. Termination
Either party may terminate for material breach with fourteen days to cure.
On termination we delete Customer Data within ninety days.
6. Liability
Our total liability is capped at the fees paid in the prior twelve months.
7. Law
This agreement is governed by the laws of Ireland."""

# (query, line id or None when the document does not answer). Ids follow the numbered non-blank lines.
FIND_CASES: list[tuple[str, str | None]] = [
    ("How often will I be billed?", "L008"),
    ("What happens if I do not pay for two months?", "L006"),
    ("How long are backups kept?", "L013"),
    ("In which country's courts would a dispute be heard?", "L021"),
    ("Is there a penalty for paying late?", "L009"),
    ("How quickly is my information erased once the contract ends?", "L017"),
    ("What is the uptime guarantee?", None),
    ("Can I resell the service to my own customers?", None),
]


def find_baseline(query: str, lines: list[str]) -> tuple[bool, str | None]:
    scores = [len(_tokens(query) & _tokens(line)) for line in lines]
    best = max(range(len(lines)), key=lambda i: scores[i])
    return (scores[best] >= 2, f"L{best + 1:03d}" if scores[best] >= 2 else None)


async def test_find_lines_beats_word_overlap(jev: Jev, board: Board) -> None:
    lines = [line.strip() for line in TERMS.splitlines() if line.strip()]
    result = await find_lines(document=TERMS, queries=[q for q, _ in FIND_CASES], tool_context=Ctx(jev))
    assert result["status"] == "success", result
    body = payload(result)
    rows: list[dict[str, Any]] = []
    for (query, truth_id), row in zip(FIND_CASES, body["results"], strict=True):
        truth = (truth_id is not None, truth_id)
        model = (row["found"], row["line_id"] if row["found"] else None)
        base = find_baseline(query, lines)
        rows.append(
            {
                "query": query,
                "truth": truth,
                "model": model,
                "baseline": base,
                "model_ok": model == truth,
                "baseline_ok": base == truth,
                "presence": row.get("presence"),
                "line": row.get("line"),
            }
        )
    card = card_from(
        jev,
        "find_lines",
        rows,
        notes="21-line contract, 8 queries (2 unanswerable); found flag and line id must both match",
    )
    board.add(card)
    card.check()


# ------------------------------------------------------------------------ extract_value

# (document, question, kind, expected verbatim value or None)
VALUE_CASES: list[tuple[str, str, str, str | None]] = [
    (
        "From: ana@x.io\nTo: billing@acme.com\n\nHi, could you send the receipt to my personal address bob.k@gmail.com rather than this one? Thanks, Bob",
        "Which email address does the sender want the receipt sent to?",
        "email",
        "bob.k@gmail.com",
    ),
    (
        "Invoice 771. Subtotal $1,200.00. Discount $200.00. Shipping $15.00. Total due $1,015.00 by Friday.",
        "What is the amount the customer has to pay?",
        "money",
        "$1,015.00",
    ),
    (
        "Order placed 2026-09-12, dispatched 2026-09-14, expected delivery 2026-09-19, returns accepted until 2026-10-19.",
        "By when must a return be started?",
        "date",
        "2026-10-19",
    ),
    (
        "Please reach the on-call engineer at +1 415 555 0100; the office line +1 415 555 0199 is unattended after 6 pm.",
        "Which number reaches someone right now, in the evening?",
        "phone",
        "+1 415 555 0100",
    ),
    (
        "Salary band: 90,000 to 120,000 USD. Sign-on bonus 10,000 USD. Relocation up to 5,000 USD on receipts.",
        "What is the one-off payment made on joining?",
        "money",
        "10,000 USD",
    ),
    (
        "Contact: press@corp.example for media, jobs@corp.example for hiring, and security@corp.example for vulnerability reports.",
        "Where should a found security hole be reported?",
        "email",
        "security@corp.example",
    ),
    (
        "Meeting notes 2026-09-01: launch moved from 2026-10-05 to 2026-11-02; the offsite stays on 2026-10-12.",
        "When is the launch now?",
        "date",
        "2026-11-02",
    ),
    (
        "Payment of $480.00 received. Outstanding balance $0.00. Previous statement showed $480.00 due.",
        "How much does the customer still owe?",
        "money",
        "$0.00",
    ),
]


def value_baseline(document: str, kind: str, candidates: list[str]) -> str | None:
    # A developer's first cut: the first span of the right kind, or the last when the text says "instead".
    if not candidates:
        return None
    return candidates[-1] if any(w in document.lower() for w in ("rather than", "instead", "moved")) else candidates[0]


async def test_extract_value_beats_first_span(jev: Jev, board: Board) -> None:
    from strands_jev.tools.cookbooks import find_candidates

    rows: list[dict[str, Any]] = []
    for document, question, kind, truth in VALUE_CASES:
        result = await extract_value(document=document, question=question, kind=kind, tool_context=Ctx(jev))
        assert result["status"] == "success", result
        body = payload(result)
        candidates = find_candidates(document, kind)
        assert truth in candidates, (truth, candidates)
        base = value_baseline(document, kind, candidates)
        rows.append(
            {
                "question": question,
                "truth": truth,
                "model": body["value"],
                "baseline": base,
                "model_ok": body["value"] == truth,
                "baseline_ok": base == truth,
                "confidence": body["confidence"],
                "candidates": candidates,
            }
        )
    card = card_from(
        jev,
        "extract_value",
        rows,
        notes="pick among regex-found spans; baseline takes the first span, or the last after 'instead'",
    )
    board.add(card)
    card.check()


# ------------------------------------------------------------------------- extract_date

TODAY = "2026-09-29"  # a Tuesday
DATE_CASES: list[tuple[str, str, str | None]] = [
    ("Payment is due on the 15th of October.", "the payment due date", "2026-10-15"),
    ("We ship tomorrow and it should arrive the day after.", "the shipping date", "2026-09-30"),
    ("Let's meet next Thursday at 10.", "the meeting date", "2026-10-08"),
    ("Can we do Thursday instead of Wednesday?", "the proposed meeting date", "2026-10-01"),
    ("The lease started March 3rd, 2019 and renews every year.", "the lease start date", "2019-03-03"),
    ("Deadline: Jan 5. Do not miss it.", "the deadline", "2027-01-05"),
    ("The invoice does not mention when it must be paid.", "the payment due date", None),
    ("Founded in 1887, the company still trades today.", "the founding date", None),
]


def date_baseline(document: str) -> str | None:
    import calendar
    from datetime import date, timedelta

    today = date.fromisoformat(TODAY)
    low = document.lower()
    if "tomorrow" in low:
        return (today + timedelta(days=1)).isoformat()
    months = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
    months.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
    match = re.search(r"(\d{1,2})(?:st|nd|rd|th)? of ([a-z]+)|([a-z]+)\.? (\d{1,2})(?:st|nd|rd|th)?,? ?(\d{4})?", low)
    if match:
        day = int(match.group(1) or match.group(4))
        month_name = match.group(2) or match.group(3)
        if month_name in months:
            year = int(match.group(5)) if match.group(5) else today.year
            try:
                return date(year, months[month_name], day).isoformat()
            except ValueError:
                return None
    for i, name in enumerate(calendar.day_name):
        if name.lower() in low:
            ahead = (i - today.weekday()) % 7
            return (today + timedelta(days=ahead + (7 if "next" in low else 0))).isoformat()
    return None


async def test_extract_date_beats_regex(jev: Jev, board: Board) -> None:
    rows: list[dict[str, Any]] = []
    for document, role, truth in DATE_CASES:
        result = await extract_date(document=document, role=role, today=TODAY, tool_context=Ctx(jev))
        assert result["status"] == "success", result
        body = payload(result)
        base = date_baseline(document)
        rows.append(
            {
                "document": document,
                "truth": truth,
                "model": body["date"],
                "baseline": base,
                "model_ok": body["date"] == truth,
                "baseline_ok": base == truth,
                "confidence": body["confidence"],
                "mode": body["mode"],
                "parts": body["parts"],
            }
        )
    card = card_from(
        jev,
        "extract_date",
        rows,
        notes="7 Choices per document, assembled in code from today=2026-09-29; baseline is a regex with weekday math",
    )
    board.add(card)
    card.check()


# --------------------------------------------------------------------- verify_citations

SOURCES = {
    "policy": (
        "Section 2. Employees may work remotely up to three days per week with manager approval. Section 3. Remote work "
        "from outside the country is not permitted without written approval from HR, and approvals are granted for at "
        "most thirty days per year. Section 4. Equipment is provided for the home office; internet costs are not "
        "reimbursed. Section 5. Core hours are 10:00 to 15:00 local time, during which employees must be reachable."
    ),
    "handbook": (
        "Holiday entitlement is 25 days per year, rising to 28 after five years of service. Unused days do not carry "
        "over unless the manager agrees in writing before December. Sick leave requires a doctor's note from the fourth "
        "consecutive day."
    ),
}
# (claim, source, quote, verdict)
CITATION_CASES = [
    (
        "Remote work is allowed three days a week with approval.",
        "policy",
        "up to three days per week with manager approval",
        "verified",
    ),
    ("The company pays for home internet.", "policy", "internet costs are not reimbursed", "contradicted"),
    (
        "Employees may work from abroad indefinitely once HR approves.",
        "policy",
        "approvals are granted for at most thirty days per year",
        "contradicted",
    ),
    (
        "Employees must be reachable in the middle of the day.",
        "policy",
        "Core hours are 10:00 to 15:00 local time",
        "verified",
    ),
    ("Holiday rises after five years.", "handbook", "rising to 28 after five years of service", "verified"),
    ("Unused holiday always carries over.", "handbook", "Unused days do not carry over", "contradicted"),
    (
        "A doctor's note is needed from the first day of sickness.",
        "handbook",
        "doctor's note from the fourth consecutive day",
        "contradicted",
    ),
    ("Employees get a company car.", "handbook", "a company car is provided", "missing_quote"),
    ("The policy covers laptops and monitors.", "policy", "Equipment is provided for the home office", "verified"),
    ("Remote workers get a stipend.", "policy", "Section 4. Equipment is provided", "unsupported"),
]


async def test_verify_citations_beats_string_match(jev: Jev, board: Board) -> None:
    rows_in = [{"claim": c, "source": s, "quote": q} for c, s, q, _ in CITATION_CASES]
    result = await verify_citations(citations=rows_in, sources=SOURCES, tool_context=Ctx(jev))
    assert result["status"] == "success", result
    body = payload(result)
    rows: list[dict[str, Any]] = []
    for (claim, source, quote, truth), row in zip(CITATION_CASES, body["results"], strict=True):
        base = "verified" if quote.lower() in SOURCES[source].lower() else "missing_quote"
        rows.append(
            {
                "claim": claim,
                "truth": truth,
                "model": row["verdict"],
                "baseline": base,
                "model_ok": row["verdict"] == truth,
                "baseline_ok": base == truth,
                "confidence": row["confidence"],
                "probabilities": row.get("probabilities"),
            }
        )
    card = card_from(
        jev, "verify_citations", rows, notes="10 citations over 2 sources; baseline calls any present quote verified"
    )
    board.add(card)
    card.check()


# ---------------------------------------------------------------------- count_matching

LOG_LINES = [
    ("2026-09-29 04:01 INFO request served in 120 ms", False),
    ("2026-09-29 04:01 WARN retrying upstream after timeout (attempt 2 of 3)", True),
    ("2026-09-29 04:02 INFO cache warmed, 1,204 keys", False),
    ("2026-09-29 04:02 ERROR upstream unreachable after 3 attempts, returning 502", True),
    ("2026-09-29 04:03 INFO health check ok", False),
    ("2026-09-29 04:03 INFO connection to db-2 re-established after 4 s", True),
    ("2026-09-29 04:04 DEBUG error budget at 97%, no action", False),
    ("2026-09-29 04:04 INFO user 42 logged in", False),
    ("2026-09-29 04:05 WARN disk 91% full on /var, cleanup scheduled", True),
    ("2026-09-29 04:05 INFO scheduled cleanup finished, disk 60% full", False),
    ("2026-09-29 04:06 ERROR payment webhook signature invalid, request rejected", True),
    ("2026-09-29 04:06 INFO the word failure appears in this release note title: 'no more silent failure'", False),
]
CONDITION = (
    "the line reports something going wrong or degraded in the running system, not a routine or informational event"
)


def count_baseline(line: str) -> bool:
    return any(word in line.lower() for word in ("error", "warn", "fail", "timeout", "unreachable", "invalid"))


async def test_count_matching_beats_keyword_grep(jev: Jev, board: Board) -> None:
    result = await count_matching(items=[line for line, _ in LOG_LINES], condition=CONDITION, tool_context=Ctx(jev))
    assert result["status"] == "success", result
    body = payload(result)
    rows: list[dict[str, Any]] = []
    for index, (line, truth) in enumerate(LOG_LINES):
        model = index in body["matching"]
        base = count_baseline(line)
        rows.append(
            {
                "line": line,
                "truth": truth,
                "model": model,
                "baseline": base,
                "model_ok": model == truth,
                "baseline_ok": base == truth,
                "p": body["probabilities"].get(str(index), body["probabilities"].get(index)),
            }
        )
    card = card_from(jev, "count_matching", rows, notes="12 log lines, one noul each; baseline greps for error words")
    board.add(card)
    card.check()
