"""jev_ask live: the three primitives on the docs' own example plus harder cases.

Baseline: keyword rules a developer would write for the same three questions (urgency from
exclamation marks and time words, team from vocabulary, frustration from anger words).
"""

from __future__ import annotations

from typing import Any

import pytest

from strands_jev import Jev, jev_ask, jev_models
from tests.conftest import payload
from tests.live.conftest import Board, Ctx, card_from

pytestmark = pytest.mark.live

QUESTIONS = {
    "urgent": {
        "type": "noul",
        "instructions": "Does this message convey urgency?",
        "criteria": {"true": "Explicitly time-sensitive or blocking", "false": "No urgency expressed"},
    },
    "team": {
        "type": "choice",
        "instructions": "Which team should handle this?",
        "criteria": {
            "billing": "Payments, invoicing, refunds, payouts",
            "technical": "Bugs, outages, integrations, API errors",
            "sales": "Pricing, upgrades, new accounts",
        },
    },
    "frustration": {
        "type": "score",
        "instructions": "How frustrated is the customer?",
        "criteria": ["Calm", "Frustrated", "Very angry"],
    },
}

# (message, urgent, team, frustration level index). The first is the docs' example
# (docs.typesafe.ai/api); the rest are written so keyword rules stumble.
CASES: list[tuple[str, bool, str, int]] = [
    ("Help! My payouts have been failing for 3 days.", True, "billing", 1),
    ("No rush at all, but when someone has a minute could you tell me what the Team plan costs?", False, "sales", 0),
    ("Third time writing. Webhooks silently drop every event since Tuesday and nobody answers.", True, "technical", 2),
    ("I would like a refund for the duplicate charge on my last invoice. Thanks.", False, "billing", 0),
    ("We go live tomorrow morning and the OAuth callback returns 500. Please look now.", True, "technical", 1),
    ("Considering moving 40 seats over from a competitor; who can walk me through pricing?", False, "sales", 0),
    ("This is unacceptable. Charged twice, no reply for a week, and now you want a screenshot?", False, "billing", 2),
    ("Quick one, whenever: is there an upgrade path from Starter to Team without a new account?", False, "sales", 0),
]


def baseline(message: str) -> tuple[bool, str, int]:
    text = message.lower()
    urgent = "!" in message or any(word in text for word in ("urgent", "now", "asap", "today", "tomorrow", "days"))
    if any(word in text for word in ("payout", "refund", "charge", "invoice", "billing")):
        team = "billing"
    elif any(word in text for word in ("bug", "error", "500", "webhook", "api", "outage", "fail")):
        team = "technical"
    else:
        team = "sales"
    angry = sum(text.count(word) for word in ("unacceptable", "nobody", "third time", "week", "!"))
    frustration = 2 if angry >= 2 else 1 if angry == 1 else 0
    return urgent, team, frustration


async def test_jev_ask_beats_keyword_rules(jev: Jev, board: Board) -> None:
    rows: list[dict[str, Any]] = []
    for message, urgent, team, level in CASES:
        result = await jev_ask(state=message, questions=QUESTIONS, tool_context=Ctx(jev))
        assert result["status"] == "success", result
        answers = payload(result)["answers"]
        model = (answers["urgent"]["noul"] >= 0.5, answers["team"]["choice"], round(answers["frustration"]["score"]))
        base = baseline(message)
        truth = (urgent, team, level)
        rows.append(
            {
                "message": message,
                "truth": truth,
                "model": model,
                "baseline": base,
                "model_ok": model == truth,
                "baseline_ok": base == truth,
                "latency_ms": payload(result)["latency_ms"],
                "input_tokens": payload(result)["input_tokens"],
                "answers": answers,
            }
        )
    card = card_from(jev, "jev_ask", rows, notes="3 questions per message, all three must match")
    board.add(card)
    card.check()


async def test_jev_models_lists_a_versioned_id(jev: Jev) -> None:
    result = await jev_models(tool_context=Ctx(jev))
    assert result["status"] == "success", result
    ids = {str(row.get("name")) for row in payload(result)["models"]}
    assert "jev-latest" in ids
