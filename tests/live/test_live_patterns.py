"""Patterns live: fan_out, route, composite_score, function_call against keyword baselines."""

from __future__ import annotations

import itertools
import re
from typing import Any

import pytest

from strands_jev import Jev, composite_score, fan_out, function_call, route
from strands_jev.questions import NO_MATCH
from tests.conftest import payload
from tests.live.conftest import Board, Ctx, card_from

pytestmark = pytest.mark.live

# ------------------------------------------------------------------------------ fan_out

TRIAGE = {
    "category": {
        "type": "choice",
        "instructions": "What kind of support ticket is this?",
        "criteria": {
            "bug_report": "Something in the product is broken or behaving wrongly",
            "billing": "Charges, invoices, refunds, payment methods",
            "feature_request": "Asking for something the product does not do",
        },
    },
    "severity": {
        "type": "score",
        "instructions": "If this is a bug, how severe is it?",
        "criteria": [
            "Cosmetic or a minor annoyance",
            "A feature is degraded but there is a workaround",
            "Core functionality is down",
        ],
    },
    "repro": "Does the ticket include concrete steps to reproduce the problem?",
    "refund": "Does the customer ask for money back?",
}
PREMISES = {
    "severity": {"question": "category", "equals": "bug_report"},
    "repro": {"question": "category", "equals": "bug_report"},
    "refund": {"question": "category", "equals": "billing"},
}

# (ticket, category, severity level or None, refund or None)
TRIAGE_CASES: list[tuple[str, str, int | None, bool | None]] = [
    (
        "Since the update nobody on my team can log in. We are locked out of everything. Tried three browsers.",
        "bug_report",
        2,
        None,
    ),
    ("The export button's tooltip says 'Exprot'. Not a big deal, just letting you know.", "bug_report", 0, None),
    (
        "Search results ignore the date filter. I can still find things by scrolling, but it is slow.",
        "bug_report",
        1,
        None,
    ),
    ("Charged twice on the 3rd for the same plan. Please put the second one back on my card.", "billing", None, True),
    (
        "Can you switch our invoices to quarterly instead of monthly? No money issue, just paperwork.",
        "billing",
        None,
        False,
    ),
    ("It would help a lot if the calendar could show two time zones side by side.", "feature_request", None, None),
    (
        "Please add dark mode. My eyes hurt at night and it is broken that you do not have it.",
        "feature_request",
        None,
        None,
    ),
    (
        "Steps: 1. open a shared doc 2. paste an image 3. the page reloads and the image is gone. Every time.",
        "bug_report",
        1,
        None,
    ),
]


TRIAGE_CASES += [
    (
        "What I would really love is for the mobile app to stop crashing every time I rotate the phone.",
        "bug_report",
        1,
        None,
    ),
    (
        "We moved to the annual plan and the amount taken was the old monthly one, times twelve. Something is off.",
        "billing",
        None,
        False,
    ),
    (
        "The receipt PDF renders the company logo upside down. Cosmetic, but our accountant noticed.",
        "bug_report",
        0,
        None,
    ),
    ("Could you take back the last payment? We were double charged when the card retried.", "billing", None, True),
]


def triage_baseline(ticket: str) -> tuple[str, int | None, bool | None]:
    text = ticket.lower()
    if any(word in text for word in ("charged", "invoice", "refund", "card", "billing")):
        category = "billing"
    elif any(word in text for word in ("would help", "please add", "could", "feature")):
        category = "feature_request"
    else:
        category = "bug_report"
    severity = None
    if category == "bug_report":
        severity = (
            2
            if any(word in text for word in ("locked out", "cannot", "down", "everything"))
            else 1
            if "slow" in text or "gone" in text
            else 0
        )
    refund = None
    if category == "billing":
        refund = any(word in text for word in ("refund", "back", "money"))
    return category, severity, refund


async def test_fan_out_beats_keyword_triage(jev: Jev, board: Board) -> None:
    rows: list[dict[str, Any]] = []
    for ticket, category, severity, refund in TRIAGE_CASES:
        result = await fan_out(state=ticket, questions=TRIAGE, premises=PREMISES, tool_context=Ctx(jev))
        assert result["status"] == "success", result
        body = payload(result)
        answers = body["answers"]
        model_category = answers["category"]["choice"]
        model_severity = round(answers["severity"]["score"]) if "severity" in answers else None
        model_refund = (answers["refund"]["noul"] >= 0.5) if "refund" in answers else None
        model = (model_category, model_severity, model_refund)
        truth = (category, severity, refund)
        base = triage_baseline(ticket)
        rows.append(
            {
                "ticket": ticket,
                "truth": truth,
                "model": model,
                "baseline": base,
                "model_ok": model == truth,
                "baseline_ok": base == truth,
                "skipped": list(body["skipped"]),
                "latency_ms": body["latency_ms"],
                "input_tokens": body["input_tokens"],
            }
        )
    card = card_from(
        jev, "fan_out", rows, notes="category plus the applicable follow-ups must all match; 4 questions per request"
    )
    board.add(card)
    card.check()


# -------------------------------------------------------------------------------- route

INTENTS = {
    "order_status": "Where an order is, tracking numbers, delivery dates",
    "product_question": "How a product works, whether it fits or is compatible, specifications",
    "return_exchange": "Sending an item back or swapping it for another",
    "complaint": "Something went wrong and the customer wants it put right",
}
HANDLERS = {
    "order_status": "code",
    "product_question": "product_llm",
    "return_exchange": "returns_llm",
    "complaint": "complaint_llm",
}

# (message, intent, handler). The handler is human when the pattern would escalate.
ROUTE_CASES: list[tuple[str, str, str]] = [
    ("Order 88213, placed Monday. Any idea when it ships?", "order_status", "code"),
    ("Will the 65W charger work with the 2019 model, or do I need the older brick?", "product_question", "product_llm"),
    ("The jacket is a size too small. How do I swap it for a large?", "return_exchange", "returns_llm"),
    (
        "Second time the driver did not ring. Box left in the rain, contents soaked. I want this fixed today.",
        "complaint",
        "human",
    ),
    ("The tracking page has said 'label created' for nine days. Is it lost?", "order_status", "code"),
    ("Does the blender jar go in the dishwasher?", "product_question", "product_llm"),
    (
        "I was promised a refund on the 2nd by your colleague and nothing has arrived. This is the fourth message.",
        "complaint",
        "human",
    ),
    ("Bought two by mistake, want to return one still sealed.", "return_exchange", "returns_llm"),
    ("Your app charged my card but shows no order. Where did my money go?", "complaint", "human"),
    ("Can you tell me a joke?", NO_MATCH, "human"),
    ("It has been sitting at the depot since Thursday according to the site. Should I worry?", "order_status", "code"),
    (
        "Is the return window still open if the box was opened but the shoes were never worn?",
        "return_exchange",
        "returns_llm",
    ),
    ("Does this order of magnitude more storage mean the drive runs hotter?", "product_question", "product_llm"),
    (
        "The size guide said medium. Medium does not fit. I would like a large instead please.",
        "return_exchange",
        "returns_llm",
    ),
]


def route_baseline(message: str) -> tuple[str, str]:
    text = message.lower()
    if any(word in text for word in ("order", "ship", "tracking", "deliver", "lost")):
        intent = "order_status"
    elif any(word in text for word in ("return", "swap", "exchange", "size")):
        intent = "return_exchange"
    elif any(word in text for word in ("work with", "compatible", "dishwasher", "does the", "will the")):
        intent = "product_question"
    elif any(word in text for word in ("refund", "charged", "promised", "soaked", "fixed")):
        intent = "complaint"
    else:
        intent = NO_MATCH
    angry = any(word in text for word in ("fourth", "second time", "today", "money go"))
    handler = (
        "human"
        if intent in {NO_MATCH, "complaint"} and (angry or intent == NO_MATCH)
        else HANDLERS.get(intent, "human")
    )
    return intent, handler


async def test_route_beats_keyword_routing(jev: Jev, board: Board) -> None:
    rows: list[dict[str, Any]] = []
    for message, intent, handler in ROUTE_CASES:
        result = await route(
            message=message, intents=INTENTS, handlers=HANDLERS, complex_intents=["complaint"], tool_context=Ctx(jev)
        )
        assert result["status"] == "success", result
        body = payload(result)
        model = (body["intent"], body["handler"])
        truth = (intent, handler)
        base = route_baseline(message)
        rows.append(
            {
                "message": message,
                "truth": truth,
                "model": model,
                "baseline": base,
                "model_ok": model == truth,
                "baseline_ok": base == truth,
                "confidence": body["confidence"],
                "reason": body["reason"],
                "complexity": body["complexity"]["score"],
                "latency_ms": jev.last_latency_ms,
            }
        )
    card = card_from(
        jev,
        "route",
        rows,
        notes="intent and handler must both match; floor 0.6; complexity gate on complaints only, as the pattern does",
    )
    board.add(card)
    card.check()


# ---------------------------------------------------------------------- composite_score

DIMENSIONS = {
    "python": "How deep is this person's Python experience?",
    "leadership": "How much have they led people, as opposed to worked alongside them?",
    "design": "How much large-scale system design have they done?",
}
PROFILES = {
    "senior_ic": {"python": 0.5, "leadership": 0.1, "design": 0.4},
    "manager": {"python": 0.15, "leadership": 0.6, "design": 0.25},
}
RESUMES = [
    "Twelve years writing Python services; maintainer of two widely used async libraries; designed the ingestion "
    "platform that handles a billion events a day. Prefers to stay hands-on; has never had direct reports.",
    "Engineering manager for six years running three teams of thirty engineers in total; sets roadmaps, hires, "
    "runs performance reviews. Wrote Django in a past life and still reviews architecture proposals.",
    "Three years as a data analyst; Python notebooks and pandas daily. Organised the team's weekly reading group.",
    "Staff engineer who led the migration of a monolith to services across four teams as tech lead, mentoring the "
    "leads of each; deep Go and Python; authored the company's service design standards.",
    "Recent graduate. Two Python internships, one Flask app in production. Captain of the university robotics club.",
    "Frontend developer. Sits next to the platform team and attends their design reviews; the company's backend is "
    "Python but I have not written any. Reports to the engineering manager. Title is lead developer, on a team of one.",
]
# Truth as a ranking per profile, best first, judged by a person reading the six texts.
TRUTH_ORDER = {"senior_ic": [0, 3, 1, 2, 4, 5], "manager": [1, 3, 0, 2, 4, 5]}


def resume_baseline(text: str) -> dict[str, float]:
    lower = text.lower()
    python = min(4, lower.count("python") + (2 if "years" in lower else 0)) / 4
    leadership = (
        min(
            4,
            sum(
                lower.count(word)
                for word in ("manager", "led", "lead", "teams", "reports", "mentoring", "captain", "organised")
            ),
        )
        / 4
    )
    design = (
        min(4, sum(lower.count(word) for word in ("design", "architecture", "platform", "migration", "services"))) / 4
    )
    return {"python": python, "leadership": leadership, "design": design}


def _pairs_correct(order: list[int], scores: dict[int, float]) -> list[bool]:
    return [scores[better] > scores[worse] for better, worse in itertools.combinations(order, 2)]


async def test_composite_score_orders_resumes_better_than_keyword_counts(jev: Jev, board: Board) -> None:
    result = await composite_score(dimensions=DIMENSIONS, items=RESUMES, weights=PROFILES, tool_context=Ctx(jev))
    assert result["status"] == "success", result
    body = payload(result)
    assert body["failures"] == 0
    rows: list[dict[str, Any]] = []
    for profile, table in PROFILES.items():
        model_scores = {row["index"]: row["composite"][profile] for row in body["results"]}
        base_scores = {
            index: sum(table[dim] * value for dim, value in resume_baseline(text).items())
            for index, text in enumerate(RESUMES)
        }
        truth = TRUTH_ORDER[profile]
        for (better, worse), model_ok, base_ok in zip(
            itertools.combinations(truth, 2),
            _pairs_correct(truth, model_scores),
            _pairs_correct(truth, base_scores),
            strict=True,
        ):
            rows.append(
                {
                    "profile": profile,
                    "pair": [better, worse],
                    "model": [model_scores[better], model_scores[worse]],
                    "baseline": [round(base_scores[better], 3), round(base_scores[worse], 3)],
                    "model_ok": model_ok,
                    "baseline_ok": base_ok,
                }
            )
    card = card_from(
        jev,
        "composite_score",
        rows,
        notes="30 ordered pairs (2 profiles x 15 pairs of 6 resumes); a pair counts when the better one scores higher",
    )
    card.rows.append({"ranking": body["ranking"], "scores": [row["scores"] for row in body["results"]]})
    board.add(card)
    card.check()


# ------------------------------------------------------------------------ function_call

TICKERS = {
    "SPY": "the S&P 500 index fund",
    "NVDA": "Nvidia",
    "AMD": "AMD",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "TSLA": "Tesla",
}
WINDOWS = {
    "1d": "today, the last day",
    "1w": "this week, the last week",
    "1mo": "this month, the last month",
    "3mo": "this quarter, the last three months",
}
FUNCTIONS = {
    "list_symbols": "List which tickers the assistant has data for",
    "market_summary": {
        "description": "How the whole market did over a period",
        "arguments": {
            "window": {
                "question": "Over what period does the user want the market summarised?",
                "stated": "Does the user name a period of time?",
                "options": WINDOWS,
            }
        },
    },
    "plot_price": {
        "description": "Draw a price chart for one ticker",
        "arguments": {
            "symbol": {"question": "Which company or fund is the chart about?", "options": TICKERS},
            "style": {
                "question": "Does the user want a plain line or candles?",
                "stated": "Does the user say how the chart should be drawn, such as a line, candles or OHLC bars?",
                "options": {"line": "a simple line through closing prices", "candles": "a candlestick or OHLC chart"},
            },
            "resolution": {
                "question": "How fine should the bars be: minutes, an hour, or a day?",
                "stated": "Does the user say how fine the bars should be, such as hourly or daily?",
                "options": {"1m": "one-minute bars", "1h": "hourly bars", "1d": "daily bars"},
            },
            "include_volume": {"question": "Does the user want trading volume shown under the price?", "kind": "flag"},
        },
    },
    "compare_returns": {
        "description": "Compare the returns of several tickers over a period",
        "arguments": {
            "symbols": {"question": "Does the user want {} in the comparison?", "kind": "set", "options": TICKERS},
            "window": {
                "question": "Over what period should the returns be compared?",
                "stated": "Does the user name a period of time?",
                "options": WINDOWS,
            },
        },
    },
    "rolling_correlation": {
        "description": "How closely one ticker has moved with another over time",
        "arguments": {
            "symbol": {"question": "Which is the ticker being measured, the one named first?", "options": TICKERS},
            "benchmark": {
                "question": "Which is the yardstick it is measured against, the second one named?",
                "options": TICKERS,
            },
            "window": {
                "question": "Over what period is the correlation measured?",
                "stated": "Does the user name a period of time?",
                "options": WINDOWS,
            },
        },
    },
    "volatility": {
        "description": "How much one ticker's price swings",
        "arguments": {"symbol": {"question": "Which company or fund is the question about?", "options": TICKERS}},
    },
    "top_movers": {
        "description": "The tickers that gained or lost the most over a period",
        "arguments": {
            "window": {
                "question": "Over what period are the movers measured?",
                "stated": "Does the user name a period of time?",
                "options": WINDOWS,
            },
            "direction": {
                "question": "Is the user asking about the biggest gainers or the biggest losers?",
                "options": {"gainers": "the ones that went up most", "losers": "the ones that went down most"},
            },
        },
    },
}

# (command, function, arguments). Taken from the cookbook's fourteen commands where our
# smaller catalogue covers them, plus a no-match.
CALL_CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("show nvda 1h", "plot_price", {"symbol": "NVDA", "resolution": "1h"}),
    (
        "plot rolling correlation between nvda and spy for the past month",
        "rolling_correlation",
        {"symbol": "NVDA", "benchmark": "SPY", "window": "1mo"},
    ),
    ("what tickers do you have", "list_symbols", {}),
    ("how did the market do this week", "market_summary", {"window": "1w"}),
    ("candles for tesla", "plot_price", {"symbol": "TSLA", "style": "candles"}),
    (
        "compare nvda amd and msft over the past three months",
        "compare_returns",
        {"symbols": ["NVDA", "AMD", "MSFT"], "window": "3mo"},
    ),
    ("how volatile is tsla", "volatility", {"symbol": "TSLA"}),
    ("biggest losers today", "top_movers", {"window": "1d", "direction": "losers"}),
    ("show me apple daily with volume", "plot_price", {"symbol": "AAPL", "resolution": "1d", "include_volume": True}),
    ("is amd tracking nvidia lately", "rolling_correlation", {"symbol": "AMD", "benchmark": "NVDA"}),
    ("book me a table for two", NO_MATCH, {}),
    ("how has microsoft been swinging", "volatility", {"symbol": "MSFT"}),
    ("which names fell hardest this quarter", "top_movers", {"window": "3mo", "direction": "losers"}),
    ("line chart of the s&p by the hour", "plot_price", {"symbol": "SPY", "style": "line", "resolution": "1h"}),
    ("what have you got data on", "list_symbols", {}),
    (
        "put nvidia and tesla side by side since the start of the month",
        "compare_returns",
        {"symbols": ["NVDA", "TSLA"], "window": "1mo"},
    ),
]

_TICKER_WORDS = {
    "nvda": "NVDA",
    "nvidia": "NVDA",
    "spy": "SPY",
    "amd": "AMD",
    "aapl": "AAPL",
    "apple": "AAPL",
    "msft": "MSFT",
    "microsoft": "MSFT",
    "tsla": "TSLA",
    "tesla": "TSLA",
}
_WINDOW_WORDS = {"today": "1d", "week": "1w", "month": "1mo", "three months": "3mo", "quarter": "3mo"}


def call_baseline(command: str) -> tuple[str, dict[str, Any]]:
    text = command.lower()
    tickers = [_TICKER_WORDS[word] for word in re.findall(r"[a-z]+", text) if word in _TICKER_WORDS]
    window = next((value for word, value in _WINDOW_WORDS.items() if word in text), None)
    args: dict[str, Any] = {}
    if "tickers" in text:
        return "list_symbols", {}
    if "market" in text:
        return "market_summary", {"window": window} if window else {}
    if "correlation" in text or "tracking" in text:
        if len(tickers) >= 2:
            args = {"symbol": tickers[0], "benchmark": tickers[1]}
        if window:
            args["window"] = window
        return "rolling_correlation", args
    if "compare" in text:
        args = {"symbols": tickers}
        if window:
            args["window"] = window
        return "compare_returns", args
    if "volatil" in text:
        return "volatility", {"symbol": tickers[0]} if tickers else {}
    if "losers" in text or "gainers" in text or "moved" in text:
        args = {"direction": "losers" if "losers" in text else "gainers"}
        if window:
            args["window"] = window
        return "top_movers", args
    if tickers:
        args = {"symbol": tickers[0]}
        if "candles" in text:
            args["style"] = "candles"
        if "1h" in text or "hourly" in text:
            args["resolution"] = "1h"
        if "daily" in text:
            args["resolution"] = "1d"
        if "volume" in text:
            args["include_volume"] = True
        return "plot_price", args
    return NO_MATCH, {}


async def test_function_call_beats_keyword_dispatch(jev: Jev, board: Board) -> None:
    rows: list[dict[str, Any]] = []
    for command, function, arguments in CALL_CASES:
        result = await function_call(request=command, functions=FUNCTIONS, tool_context=Ctx(jev))
        assert result["status"] == "success", result
        body = payload(result)
        model = (body["function"], body["arguments"])
        truth = (function, arguments)
        base = call_baseline(command)
        rows.append(
            {
                "command": command,
                "truth": truth,
                "model": model,
                "baseline": base,
                "model_ok": model == truth,
                "baseline_ok": base == truth,
                "confidence": body["confidence"],
                "questions_sent": body["questions_sent"],
                "latency_ms": body["latency_ms"],
            }
        )
    card = card_from(
        jev, "function_call", rows, notes="function and every argument must match exactly; one request per command"
    )
    board.add(card)
    card.check()
