"""rerank, find_lines, extract_value, extract_date, verify_citations, count_matching on the scripted endpoint."""

from __future__ import annotations

from datetime import date
from typing import Any

from strands import Agent
from strands.models import BedrockModel
from typesafe_sdk import Choice, Noul

from strands_jev import ALL_TOOLS, count_matching, extract_date, extract_value, find_lines, rerank, verify_citations
from strands_jev.questions import EXTRACT_VALUE_NONE
from strands_jev.tools.cookbooks import MONTHS, assemble_date, find_candidates
from tests.conftest import FakeJev, choice, noul, payload, summary


def _ctx(fake: FakeJev) -> Any:
    class Ctx:
        invocation_state = {"jev": fake}

    return Ctx()


# ------------------------------------------------------------------------------ rerank


async def test_rerank_sorts_by_probability_and_returns_best_in_full() -> None:
    def responder(state: Any, questions: Any) -> dict[str, Any]:
        return {"match": noul({"a": 0.2, "b": 0.9, "c": 0.5}[state["candidate"]["id"]])}

    fake = FakeJev(responder=responder)
    items = [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}, {"id": "c", "text": "z"}]
    result = await rerank(query="which?", candidates=items, top_k=2, tool_context=_ctx(fake))
    body = payload(result)
    assert fake.call_count == 3
    assert [row["index"] for row in body["ranked"]] == [1, 2]
    assert body["best"] == items[1]
    assert summary(result) == "best #1 at 0.90; 2 of 3 returned"
    assert fake.last_state["query"] == "which?"
    assert isinstance(fake.last_questions["match"], Noul)


async def test_rerank_custom_instructions_and_refusals(fake: FakeJev) -> None:
    await rerank(query="q", candidates=["a"], instructions="Is it the cited case?", tool_context=_ctx(fake))
    assert fake.last_questions["match"].instructions == "Is it the cited case?"
    assert "between 1 and 2" in summary(
        await rerank(query="q", candidates=["a", "b"], top_k=5, tool_context=_ctx(fake))
    )
    assert "empty" in summary(await rerank(query="q", candidates=[], tool_context=_ctx(fake)))


async def test_rerank_keeps_failures_per_item() -> None:
    calls = {"n": 0}

    def responder(state: Any, questions: Any) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 2:
            raise TimeoutError("slow")
        return {"match": noul(0.7)}

    result = await rerank(query="q", candidates=["a", "b", "c"], tool_context=_ctx(FakeJev(responder=responder)))
    body = payload(result)
    assert len(body["ranked"]) == 2 and body["failures"][0]["index"] == 1
    assert summary(result).endswith("1 failed")


# --------------------------------------------------------------------------- find_lines

DOC = (
    "Title\n\nYou own your content.\nWe may suspend accounts that break the rules.\nRefunds are issued within 14 days."
)


async def test_find_lines_numbers_lines_and_reads_presence() -> None:
    def responder(state: Any, questions: Any) -> dict[str, Any]:
        query = questions["where"].instructions
        if "refund" in query:
            return {
                "where": choice("L004", {"L001": 0.0, "L002": 0.05, "L003": 0.05, "L004": 0.9}),
                "exists": noul(0.95),
            }
        return {"where": choice("L002", {"L001": 0.1, "L002": 0.5, "L003": 0.3, "L004": 0.1}), "exists": noul(0.08)}

    fake = FakeJev(responder=responder)
    result = await find_lines(
        document=DOC, queries=["how long do refunds take?", "what is the price?"], tool_context=_ctx(fake)
    )
    body = payload(result)
    assert body["lines"] == 4 and fake.call_count == 2
    assert fake.calls[0][0].startswith("L001| Title\nL002| You own your content.")
    assert set(fake.last_questions["where"].criteria) == {"L001", "L002", "L003", "L004"}
    first, second = body["results"]
    assert first["found"] and first["line_id"] == "L004" and first["line"] == "Refunds are issued within 14 days."
    assert first["runners_up"][0]["line_id"] in {"L002", "L003"}
    assert not second["found"] and second["presence"] == 0.08
    assert (
        summary(result) == "2/2 found: L004 (0.95), not found (0.08)"
        or summary(result) == "1/2 found: L004 (0.95), not found (0.08)"
    )


async def test_find_lines_windows_long_documents() -> None:
    lines = [f"line {i}" for i in range(600)]

    def responder(state: Any, questions: Any) -> dict[str, Any]:
        ids = list(questions["where"].criteria)
        hit = "L400" in ids
        return {
            "where": choice(
                ids[0] if not hit else "L400", {i: 0.0 for i in ids} | {(ids[0] if not hit else "L400"): 1.0}
            ),
            "exists": noul(0.9 if hit else 0.05),
        }

    fake = FakeJev(responder=responder)
    body = payload(await find_lines(document=lines, queries="where is 399?", tool_context=_ctx(fake)))
    assert body["windows"] == 3 and fake.call_count == 3
    assert body["results"][0]["line_id"] == "L400" and body["results"][0]["line"] == "line 399"
    assert len(fake.calls[2][1]["where"].criteria) == 90


async def test_find_lines_refusals(fake: FakeJev) -> None:
    assert "document is empty" in summary(await find_lines(document="\n\n", queries=["q"], tool_context=_ctx(fake)))
    assert "between 0 and 1" in summary(
        await find_lines(document=DOC, queries=["q"], min_presence=3, tool_context=_ctx(fake))
    )


# ------------------------------------------------------------------------ extract_value


def test_find_candidates_kinds() -> None:
    text = "Mail ana@x.io or bob@y.org, pay $1,200.50 or 300 EUR by 2026-09-30, call +1 415 555 0100. Also 12%."
    assert find_candidates(text, "email") == ["ana@x.io", "bob@y.org"]
    assert find_candidates(text, "money") == ["$1,200.50", "300 EUR"]
    assert find_candidates(text, "date") == ["2026-09-30"]
    assert find_candidates(text, "percent") == ["12%"]
    assert find_candidates(text, "phone") == ["+1 415 555 0100"]


async def test_extract_value_picks_verbatim_with_none_hatch() -> None:
    fake = FakeJev({"pick": choice("bob@y.org", {"ana@x.io": 0.1, "bob@y.org": 0.85, EXTRACT_VALUE_NONE: 0.05})})
    doc = "From: ana@x.io. Please send the receipt to bob@y.org instead."
    result = await extract_value(
        document=doc, question="Which address should the receipt go to?", kind="email", tool_context=_ctx(fake)
    )
    body = payload(result)
    assert body["value"] == "bob@y.org" and body["decided"] and body["candidates"] == ["ana@x.io", "bob@y.org"]
    assert EXTRACT_VALUE_NONE in fake.last_questions["pick"].criteria
    assert summary(result) == "'bob@y.org' (0.85)"


async def test_extract_value_single_candidate_becomes_a_noul_and_none_is_null() -> None:
    fake = FakeJev({"pick": noul(0.2)})
    body = payload(
        await extract_value(
            document="call 555 0100 2000",
            question="the fax number?",
            candidates=["555 0100 2000"],
            tool_context=_ctx(fake),
        )
    )
    assert body["value"] is None and body["confidence"] == 0.8
    assert isinstance(fake.last_questions["pick"], Noul)
    fake = FakeJev({"pick": choice(EXTRACT_VALUE_NONE, {"a": 0.2, "b": 0.2, EXTRACT_VALUE_NONE: 0.6})})
    result = await extract_value(document="d", question="q", candidates=["a", "b"], tool_context=_ctx(fake))
    assert payload(result)["value"] is None and summary(result) == "none of 2 candidates (0.60)"


async def test_extract_value_no_spans_and_refusals(fake: FakeJev) -> None:
    result = await extract_value(document="nothing here", question="q", kind="email", tool_context=_ctx(fake))
    assert result["status"] == "success" and payload(result)["value"] is None and fake.call_count == 0
    assert "give candidates" in summary(await extract_value(document="d", question="q", tool_context=_ctx(fake)))
    assert "unknown candidate kind" in summary(
        await extract_value(document="d", question="q", kind="colour", tool_context=_ctx(fake))
    )


# ------------------------------------------------------------------------- extract_date

TODAY = date(2026, 9, 29)  # a Tuesday


def _parts(**choices: str) -> dict[str, Any]:
    defaults = {
        "mode": "none",
        "month": "none",
        "day": "none",
        "year": "none",
        "day_anchor": "none",
        "weekday": "none",
        "week_offset": "none",
    }
    defaults.update(choices)
    return {key: choice(value, {value: 0.9}) for key, value in defaults.items()}


def test_assemble_date_cases() -> None:
    assert assemble_date(_parts(mode="absolute", month="March", day="3", year="2027"), TODAY)["date"] == "2027-03-03"
    inferred = assemble_date(_parts(mode="absolute", month="March", day="3"), TODAY)
    assert inferred["date"] == "2027-03-03" and inferred["year_inferred"]
    assert assemble_date(_parts(mode="absolute", month="October", day="1"), TODAY)["date"] == "2026-10-01"
    assert assemble_date(_parts(mode="relative", day_anchor="tomorrow"), TODAY)["date"] == "2026-09-30"
    assert (
        assemble_date(_parts(mode="relative", day_anchor="weekday", weekday="Thursday"), TODAY)["date"] == "2026-10-01"
    )
    assert (
        assemble_date(_parts(mode="relative", day_anchor="weekday", weekday="Thursday", week_offset="next"), TODAY)[
            "date"
        ]
        == "2026-10-08"
    )
    assert (
        assemble_date(_parts(mode="relative", day_anchor="weekday", weekday="Tuesday"), TODAY)["date"] == "2026-09-29"
    )
    assert (
        assemble_date(_parts(mode="absolute", month="February", day="30", year="2026"), TODAY)["problem"]
        == "no such day"
    )
    assert (
        assemble_date(_parts(mode="absolute", month="May", day="1", year="out_of_range"), TODAY)["problem"]
        == "year out of range"
    )
    assert assemble_date(_parts(), TODAY)["date"] is None


async def test_extract_date_tool_gates_on_weakest_part() -> None:
    parts = _parts(mode="absolute", month="March", day="3", year="2027")
    parts["day"] = choice("3", {"3": 0.4, "4": 0.35})
    fake = FakeJev(parts)
    result = await extract_date(
        document="due the 3rd of March 2027", role="the due date", today="2026-09-29", tool_context=_ctx(fake)
    )
    body = payload(result)
    assert body["date"] == "2027-03-03" and body["confidence"] == 0.4 and not body["decided"]
    assert summary(result) == "2027-03-03 (absolute, 0.40) under the floor, review"
    assert len(fake.last_questions) == 7 and list(fake.last_questions["month"].criteria)[:12] == MONTHS
    assert "must be an ISO date" in summary(
        await extract_date(document="d", role="r", today="yesterday", tool_context=_ctx(fake))
    )
    assert "role is empty" in summary(await extract_date(document="d", role=" ", tool_context=_ctx(fake)))


# --------------------------------------------------------------------- verify_citations

SOURCES = {
    "terms": "Section 4. Refunds are issued within 14 days of a request. Section 5. Accounts may be closed for abuse."
}


async def test_verify_citations_string_match_then_choice() -> None:
    def responder(state: Any, questions: Any) -> dict[str, Any]:
        if "30 days" in state["claim"]:
            return {"relation": choice("contradicts", {"supports": 0.05, "contradicts": 0.9, "says_nothing": 0.05})}
        return {"relation": choice("supports", {"supports": 0.5, "contradicts": 0.1, "says_nothing": 0.4})}

    fake = FakeJev(responder=responder)
    citations = [
        {"claim": "Refunds take 30 days", "source": "terms", "quote": "issued within 14 days"},
        {"claim": "Abuse leads to suspension", "source": "terms", "quote": "closed for abuse"},
        {"claim": "Fees are waived", "source": "terms", "quote": "fees are waived"},
        {"claim": "Anything", "source": "privacy", "quote": "x"},
    ]
    result = await verify_citations(citations=citations, sources=SOURCES, tool_context=_ctx(fake))
    body = payload(result)
    assert fake.call_count == 2
    verdicts = [row["verdict"] for row in body["results"]]
    assert verdicts == ["contradicted", "verified", "missing_quote", "unknown_source"]
    assert body["results"][1]["decided"] is False and body["review"] == 1
    assert "section" in fake.calls[0][0] and isinstance(fake.last_questions["relation"], Choice)
    assert summary(result) == "contradicted 1, missing_quote 1, unknown_source 1, verified 1; 1 under the floor"


async def test_verify_citations_refuses_bad_rows(fake: FakeJev) -> None:
    assert "needs claim, source and quote" in summary(
        await verify_citations(citations=[{"claim": "c"}], sources=SOURCES, tool_context=_ctx(fake))
    )
    assert fake.call_count == 0


# ---------------------------------------------------------------------- count_matching


async def test_count_matching_counts_in_code() -> None:
    def responder(state: Any, questions: Any) -> dict[str, Any]:
        return {"match": noul(0.9 if "error" in state else 0.1)}

    fake = FakeJev(responder=responder)
    result = await count_matching(
        items=["ok", "error: disk", "warn", "error: net"],
        condition="the line reports an error",
        tool_context=_ctx(fake),
    )
    body = payload(result)
    assert body["count"] == 2 and body["matching"] == [1, 3] and fake.call_count == 4
    assert fake.last_questions["match"].instructions == "Does this item satisfy: the line reports an error?"
    assert summary(result) == "2 of 4 match"
    assert "condition is empty" in summary(await count_matching(items=["a"], condition=" ", tool_context=_ctx(fake)))


def test_direct_agent_calls_for_every_cookbook_tool() -> None:
    agent = Agent(
        model=BedrockModel(model_id="never-called", region_name="us-east-1"), tools=ALL_TOOLS, callback_handler=None
    )
    assert (
        payload(agent.tool.rerank(query="q", candidates=["a", "b"], jev=FakeJev({"match": noul(0.6)})))["best"] == "a"
    )
    fake = FakeJev({"where": choice("L001", {"L001": 1.0}), "exists": noul(0.9)})
    assert payload(agent.tool.find_lines(document="one line", queries=["q"], jev=fake))["results"][0]["found"]
    fake = FakeJev({"pick": choice("a", {"a": 0.9, "b": 0.05, EXTRACT_VALUE_NONE: 0.05})})
    assert (
        payload(agent.tool.extract_value(document="a b", question="q", candidates=["a", "b"], jev=fake))["value"] == "a"
    )
    fake = FakeJev(_parts(mode="relative", day_anchor="today"))
    assert (
        payload(agent.tool.extract_date(document="today", role="r", today="2026-09-29", jev=fake))["date"]
        == "2026-09-29"
    )
    fake = FakeJev({"relation": choice("supports", {"supports": 0.9, "contradicts": 0.05, "says_nothing": 0.05})})
    rows = [{"claim": "c", "source": "terms", "quote": "14 days"}]
    assert (
        payload(agent.tool.verify_citations(citations=rows, sources=SOURCES, jev=fake))["results"][0]["verdict"]
        == "verified"
    )
    assert (
        payload(agent.tool.count_matching(items=["a", "b"], condition="c", jev=FakeJev({"match": noul(0.9)})))["count"]
        == 2
    )
