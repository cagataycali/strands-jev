"""fan_out, route, composite_score, function_call against the scripted endpoint."""

from __future__ import annotations

from typing import Any

from strands import Agent
from strands.models import BedrockModel
from typesafe_sdk import Choice, Noul, Score

from strands_jev import ALL_TOOLS, composite_score, fan_out, function_call, route
from strands_jev.questions import NO_MATCH, ROUTE_COMPLEXITY_LEVELS
from tests.conftest import FakeJev, choice, noul, payload, score, summary


def _ctx(fake: FakeJev) -> Any:
    class Ctx:
        invocation_state = {"jev": fake}

    return Ctx()


TRIAGE = {
    "category": {
        "type": "choice",
        "instructions": "What kind of ticket?",
        "criteria": ["bug_report", "billing", "feature"],
    },
    "severity": {"type": "score", "instructions": "How severe?", "criteria": ["cosmetic", "degraded", "down"]},
    "repro": "Does the ticket include steps to reproduce?",
    "refund": "Does the customer ask for a refund?",
    "frustration": {"type": "score", "instructions": "How frustrated?", "criteria": ["calm", "annoyed", "angry"]},
}
PREMISES = {
    "severity": {"question": "category", "equals": "bug_report"},
    "repro": {"question": "category", "equals": "bug_report"},
    "refund": {"question": "category", "equals": "billing"},
}


async def test_fan_out_keeps_applicable_and_reports_skipped() -> None:
    fake = FakeJev(
        {
            "category": choice("bug_report", {"bug_report": 0.9, "billing": 0.05, "feature": 0.05}),
            "severity": score(2.0, ["cosmetic", "degraded", "down"]),
            "repro": noul(0.8),
            "refund": noul(0.1),
            "frustration": score(1.0, ["calm", "annoyed", "angry"]),
        }
    )
    result = await fan_out(
        state="the app crashes on login, steps below", questions=TRIAGE, premises=PREMISES, tool_context=_ctx(fake)
    )
    assert result["status"] == "success", result
    body = payload(result)
    assert fake.call_count == 1 and len(fake.last_questions) == 5
    assert set(body["answers"]) == {"category", "severity", "repro", "frustration"}
    assert list(body["skipped"]) == ["refund"]
    assert body["skipped"]["refund"]["because"] == "category=bug_report"
    assert body["skipped"]["refund"]["answer"]["noul"] == 0.1
    assert summary(result) == "4 applicable, 1 skipped (refund)"


async def test_fan_out_at_least_premise_on_noul_and_score() -> None:
    fake = FakeJev({"gate": noul(0.75), "sev": score(0.5, ["a", "b", "c"]), "follow": noul(0.9), "other": noul(0.2)})
    result = await fan_out(
        state="x",
        questions={
            "gate": "g?",
            "sev": {"type": "score", "instructions": "s", "criteria": ["a", "b", "c"]},
            "follow": "f?",
            "other": "o?",
        },
        premises={"follow": {"question": "gate", "at_least": 0.7}, "other": {"question": "sev", "at_least": 1.5}},
        tool_context=_ctx(fake),
    )
    body = payload(result)
    assert "follow" in body["answers"] and "other" in body["skipped"]


async def test_fan_out_refuses_bad_premises(fake: FakeJev) -> None:
    result = await fan_out(
        state="x", questions={"a": "a?"}, premises={"b": {"question": "a", "equals": True}}, tool_context=_ctx(fake)
    )
    assert result["status"] == "error" and "not one of the questions" in summary(result)
    result = await fan_out(
        state="x",
        questions={"a": "a?", "b": "b?"},
        premises={"b": {"question": "zzz", "equals": True}},
        tool_context=_ctx(fake),
    )
    assert result["status"] == "error" and "not a question in this request" in summary(result)
    result = await fan_out(state="x", questions={"a": "a?", "b": "b?"}, premises={"b": "a"}, tool_context=_ctx(fake))
    assert result["status"] == "error" and "must be a dict" in summary(result)
    assert fake.call_count == 0


INTENTS = {
    "order_status": "Where is my order, tracking, delivery dates",
    "product_question": "How a product works, compatibility, specs",
    "return_exchange": "Returning or swapping an item",
    "complaint": "Something went wrong and the customer is unhappy",
}


async def test_route_decides_and_maps_handlers() -> None:
    fake = FakeJev(
        {
            "intent": choice(
                "order_status",
                {
                    "order_status": 0.9,
                    "product_question": 0.05,
                    "return_exchange": 0.03,
                    "complaint": 0.02,
                    NO_MATCH: 0.0,
                },
            ),
            "complexity": score(0.2, ROUTE_COMPLEXITY_LEVELS, {0: 0.8, 1: 0.2, 2: 0.0}),
        }
    )
    result = await route(
        message="where is order 123?", intents=INTENTS, handlers={"order_status": "code"}, tool_context=_ctx(fake)
    )
    body = payload(result)
    assert body["decided"] and body["handler"] == "code" and not body["escalate"]
    assert body["runner_up"] == "product_question"
    assert body["complexity"]["score"] == 0.2
    assert summary(result) == "order_status (0.90) -> code"
    sent = fake.last_questions
    assert isinstance(sent["intent"], Choice) and NO_MATCH in sent["intent"].criteria
    assert isinstance(sent["complexity"], Score)


async def test_route_escalates_on_complexity_and_low_confidence() -> None:
    complaint = choice(
        "complaint",
        {"complaint": 0.7, "return_exchange": 0.2, "order_status": 0.05, "product_question": 0.05, NO_MATCH: 0.0},
    )
    fake = FakeJev({"intent": complaint, "complexity": score(1.6, ROUTE_COMPLEXITY_LEVELS, {0: 0.0, 1: 0.4, 2: 0.6})})
    body = payload(await route(message="x", intents=INTENTS, tool_context=_ctx(fake)))
    assert body["decided"] and body["escalate"] and body["handler"] == "human"
    assert body["reason"] == "complexity 1.60 is above 1"

    fake = FakeJev({"intent": complaint, "complexity": score(0.9, ROUTE_COMPLEXITY_LEVELS, {0: 0.4, 1: 0.3, 2: 0.3})})
    body = payload(await route(message="x", intents=INTENTS, tool_context=_ctx(fake)))
    assert body["escalate"] and "complexity confidence 0.40 is under 0.5" in body["reason"]

    fake = FakeJev({"intent": complaint})
    body = payload(
        await route(
            message="x",
            intents=INTENTS,
            thresholds={"complaint": 0.85},
            assess_complexity=False,
            tool_context=_ctx(fake),
        )
    )
    assert not body["decided"] and body["handler"] == "human" and body["threshold_used"] == 0.85
    assert "complexity" not in body and len(fake.last_questions) == 1


async def test_route_no_match_goes_to_a_person() -> None:
    fake = FakeJev(
        {
            "intent": choice(
                NO_MATCH,
                {NO_MATCH: 0.8, "complaint": 0.2, "order_status": 0, "product_question": 0, "return_exchange": 0},
            )
        }
    )
    body = payload(await route(message="x", intents=INTENTS, assess_complexity=False, tool_context=_ctx(fake)))
    assert body["intent"] == NO_MATCH and not body["decided"] and body["reason"] == "no listed intent applies"


async def test_route_refusals(fake: FakeJev) -> None:
    assert "at least two" in summary(await route(message="x", intents=["only"], tool_context=_ctx(fake)))
    assert "reserved" in summary(await route(message="x", intents=[NO_MATCH, "a"], tool_context=_ctx(fake)))
    assert "not listed" in summary(
        await route(message="x", intents=INTENTS, thresholds={"zzz": 0.5}, tool_context=_ctx(fake))
    )
    assert "not listed" in summary(
        await route(message="x", intents=INTENTS, handlers={"zzz": "code"}, tool_context=_ctx(fake))
    )
    assert "between 0 and 1" in summary(
        await route(message="x", intents=INTENTS, min_confidence=2, tool_context=_ctx(fake))
    )
    assert fake.call_count == 0


DIMS = {"python": "How deep is the Python experience?", "leadership": "How much team leadership?"}


async def test_composite_score_one_state_with_profiles() -> None:
    fake = FakeJev(
        {"python": score(4.0, ["a", "b", "c", "d", "e"]), "leadership": score(1.0, ["a", "b", "c", "d", "e"])}
    )
    result = await composite_score(
        dimensions=DIMS,
        state="resume text",
        weights={"senior_ic": {"python": 0.8, "leadership": 0.2}, "manager": {"python": 0.2, "leadership": 0.8}},
        tool_context=_ctx(fake),
    )
    body = payload(result)
    row = body["results"][0]
    assert row["scores"]["python"]["normalised"] == 1.0 and row["scores"]["leadership"]["normalised"] == 0.25
    assert row["composite"] == {"senior_ic": 0.85, "manager": 0.4}
    assert body["profiles"]["senior_ic"] == {"python": 0.8, "leadership": 0.2}
    assert summary(result) == "composite senior_ic=0.85, manager=0.40"
    assert len(fake.last_questions["python"].criteria) == 5


async def test_composite_score_ranks_items_with_own_levels() -> None:
    def responder(state: Any, questions: Any) -> dict[str, Any]:
        depth = {"junior": 1.0, "senior": 3.0, "staff": 4.0}[state]
        return {
            "python": score(depth, ["a", "b", "c", "d", "e"]),
            "leadership": score(1.0, ["none", "lead", "manager"]),
        }

    fake = FakeJev(responder=responder)
    result = await composite_score(
        dimensions={
            "python": DIMS["python"],
            "leadership": {"instructions": "lead?", "levels": ["none", "lead", "manager"]},
        },
        items=["junior", "senior", "staff"],
        tool_context=_ctx(fake),
    )
    body = payload(result)
    assert fake.call_count == 3
    assert body["ranking"]["equal"] == [2, 1, 0]
    assert body["results"][0]["scores"]["leadership"]["normalised"] == 0.5
    assert summary(result).startswith("3 items ranked; best equal: #2")


async def test_composite_score_refusals(fake: FakeJev) -> None:
    assert "exactly one of state" in summary(await composite_score(dimensions=DIMS, tool_context=_ctx(fake)))
    assert "exactly one of state" in summary(
        await composite_score(dimensions=DIMS, state="a", items=["b"], tool_context=_ctx(fake))
    )
    assert "not listed" in summary(
        await composite_score(dimensions=DIMS, state="a", weights={"zzz": 1}, tool_context=_ctx(fake))
    )
    assert "sum to 0" in summary(
        await composite_score(dimensions=DIMS, state="a", weights={"python": 0}, tool_context=_ctx(fake))
    )
    assert "not be negative" in summary(
        await composite_score(dimensions=DIMS, state="a", weights={"python": -1}, tool_context=_ctx(fake))
    )
    assert "needs between 2 and 10" in summary(
        await composite_score(dimensions=DIMS, state="a", levels=["one"], tool_context=_ctx(fake))
    )
    assert fake.call_count == 0


FUNCTIONS = {
    "list_symbols": "List the tickers the assistant knows",
    "plot_price": {
        "description": "Draw a price chart for one ticker",
        "arguments": {
            "symbol": {
                "question": "Which ticker is the chart about?",
                "options": {"SPY": "the S&P 500 fund", "NVDA": "Nvidia", "AAPL": "Apple"},
            },
            "style": {
                "question": "A plain line or candles?",
                "stated": "Does the user say how to draw the chart?",
                "options": {"line": "a line", "candles": "candlesticks"},
            },
            "include_volume": {"question": "Does the user want volume shown?", "kind": "flag"},
        },
    },
    "compare_returns": {
        "description": "Compare several tickers' returns",
        "arguments": {
            "symbols": {
                "question": "Does the user want {} in the comparison?",
                "kind": "set",
                "options": ["SPY", "NVDA", "AAPL"],
            }
        },
    },
}


async def test_function_call_reads_only_the_chosen_function() -> None:
    fake = FakeJev(
        {
            "__tool__": choice(
                "plot_price", {"plot_price": 0.9, "list_symbols": 0.05, "compare_returns": 0.05, NO_MATCH: 0.0}
            ),
            "plot_price.symbol": choice("AAPL", {"AAPL": 0.95, "SPY": 0.03, "NVDA": 0.02}),
            "plot_price.style?": noul(0.1),
            "plot_price.style": choice("candles", {"candles": 0.6, "line": 0.4}),
            "plot_price.include_volume": noul(0.85),
            "compare_returns.symbols.AAPL": noul(0.99),
        }
    )
    result = await function_call(request="show me apple with volume", functions=FUNCTIONS, tool_context=_ctx(fake))
    body = payload(result)
    assert body["function"] == "plot_price"
    assert body["arguments"] == {"symbol": "AAPL", "include_volume": True}
    assert body["per_argument"]["style"]["stated"] is False and body["per_argument"]["style"]["value"] == "candles"
    assert body["confidence"] == 0.85 and body["decided"]
    assert body["questions_sent"] == 8
    assert summary(result) == "plot_price(symbol='AAPL', include_volume=True) confidence 0.85"
    sent = fake.last_questions
    assert isinstance(sent["compare_returns.symbols.NVDA"], Noul)
    assert sent["compare_returns.symbols.NVDA"].instructions == "Does the user want NVDA in the comparison?"
    assert NO_MATCH in sent["__tool__"].criteria


async def test_function_call_set_argument_and_no_match() -> None:
    fake = FakeJev(
        {
            "__tool__": choice(
                "compare_returns", {"compare_returns": 0.7, "plot_price": 0.3, "list_symbols": 0, NO_MATCH: 0}
            ),
            "compare_returns.symbols.SPY": noul(0.2),
            "compare_returns.symbols.NVDA": noul(0.9),
            "compare_returns.symbols.AAPL": noul(0.8),
        }
    )
    body = payload(await function_call(request="nvda vs apple", functions=FUNCTIONS, tool_context=_ctx(fake)))
    assert body["arguments"] == {"symbols": ["NVDA", "AAPL"]} and body["confidence"] == 0.7

    fake = FakeJev(
        {"__tool__": choice(NO_MATCH, {NO_MATCH: 0.9, "compare_returns": 0.1, "plot_price": 0, "list_symbols": 0})}
    )
    result = await function_call(request="what is the weather", functions=FUNCTIONS, tool_context=_ctx(fake))
    body = payload(result)
    assert body["function"] == NO_MATCH and not body["decided"] and body["arguments"] == {}
    assert summary(result).endswith("(not decided)")


async def test_function_call_refusals(fake: FakeJev) -> None:
    bad = {"f": {"description": "d", "arguments": {"a": {"options": {"x": 1, "y": 2}}}}}
    assert "needs a 'question'" in summary(await function_call(request="x", functions=bad, tool_context=_ctx(fake)))
    bad = {"f": {"description": "d", "arguments": {"a": {"question": "q", "options": ["only"]}}}}
    assert "at least two options" in summary(await function_call(request="x", functions=bad, tool_context=_ctx(fake)))
    bad = {"f": {"description": "d", "arguments": {"a": {"question": "q", "kind": "set"}}}}
    assert "needs 'options'" in summary(await function_call(request="x", functions=bad, tool_context=_ctx(fake)))
    bad = {"f": {"description": "d", "arguments": {"a": {"question": "q", "kind": "number"}}}}
    assert "kind must be choice, set or flag" in summary(
        await function_call(request="x", functions=bad, tool_context=_ctx(fake))
    )
    big = {
        f"f{i}": {"description": "d", "arguments": {f"a{j}": {"question": "q", "kind": "flag"} for j in range(20)}}
        for i in range(7)
    }
    assert "over the ceiling" in summary(await function_call(request="x", functions=big, tool_context=_ctx(fake)))
    assert fake.call_count == 0


def test_direct_agent_calls_for_every_pattern_tool() -> None:
    agent = Agent(
        model=BedrockModel(model_id="never-called", region_name="us-east-1"), tools=ALL_TOOLS, callback_handler=None
    )
    fake = FakeJev({"intent": choice("a", {"a": 0.9, "b": 0.1, NO_MATCH: 0.0})})
    result = agent.tool.route(message="m", intents=["a", "b"], assess_complexity=False, jev=fake)
    assert result["status"] == "success" and payload(result)["intent"] == "a"
    result = agent.tool.fan_out(state="s", questions={"a": "a?"}, jev=FakeJev({"a": noul(0.7)}))
    assert payload(result)["answers"]["a"]["noul"] == 0.7
    result = agent.tool.composite_score(dimensions=DIMS, state="s", jev=FakeJev())
    assert result["status"] == "success" and "composite" in payload(result)["results"][0]
    result = agent.tool.function_call(
        request="r", functions={"f": "does f"}, jev=FakeJev({"__tool__": choice("f", {"f": 1.0, NO_MATCH: 0.0})})
    )
    assert payload(result)["function"] == "f" and payload(result)["decided"]
