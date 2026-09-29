"""jev_ask, jev_models, jev_usage against the scripted endpoint, plus one call through a real Agent."""

from __future__ import annotations

from typing import Any

from strands import Agent
from strands.models import BedrockModel
from typesafe_sdk import Choice, Noul, Score

from strands_jev import ALL_TOOLS, Jev, configure, jev_ask, jev_models, jev_usage
from strands_jev.tools import _common
from tests.conftest import FakeJev, choice, noul, payload, score, summary


def _ctx(fake: FakeJev) -> Any:
    class Ctx:
        invocation_state = {"jev": fake}

    return Ctx()


async def test_ask_mixed_question_types(fake: FakeJev) -> None:
    fake._answers = {
        "urgent": noul(0.91),
        "team": choice("billing", {"billing": 0.8, "technical": 0.2}),
        "anger": score(1.5, ["calm", "frustrated", "angry"]),
    }
    result = await jev_ask(
        state="Help! My payouts have been failing for 3 days.",
        questions={
            "urgent": {"type": "noul", "instructions": "Does this convey urgency?"},
            "team": {
                "type": "choice",
                "instructions": "Which team?",
                "criteria": {"billing": "money", "technical": "bugs"},
            },
            "anger": {"type": "score", "instructions": "How angry?", "criteria": ["calm", "frustrated", "angry"]},
        },
        tool_context=_ctx(fake),
    )
    assert result["status"] == "success"
    body = payload(result)
    assert body["answers"]["urgent"] == {"type": "noul", "noul": 0.91}
    assert body["answers"]["team"]["choice"] == "billing"
    assert body["answers"]["anger"]["legend"][2] == "angry"
    assert body["model"] == "jev-fake"
    assert summary(result) == "3 answers: urgent=0.91, team=billing (0.80), anger=1.50 (1.00)"
    sent = fake.last_questions
    assert isinstance(sent["urgent"], Noul) and isinstance(sent["team"], Choice) and isinstance(sent["anger"], Score)


async def test_ask_tolerates_json_string_and_bare_strings(fake: FakeJev) -> None:
    result = await jev_ask(state="x", questions='["is it red?", "is it round?"]', tool_context=_ctx(fake))
    assert result["status"] == "success"
    assert list(fake.last_questions) == ["q1", "q2"]
    assert fake.last_questions["q1"].instructions == "is it red?"


async def test_ask_accepts_option_list_for_choice_and_structured_instructions(fake: FakeJev) -> None:
    result = await jev_ask(
        state={"resume": "..."},
        questions={
            "same": {
                "type": "choice",
                "instructions": {"who": {"name": "A"}, "question": "same as `who`?"},
                "criteria": ["yes", "no", "unclear"],
            }
        },
        tool_context=_ctx(fake),
    )
    assert result["status"] == "success"
    assert fake.last_questions["same"].criteria == {"yes": None, "no": None, "unclear": None}


async def test_ask_refuses_bad_specs_before_spending(fake: FakeJev) -> None:
    cases = [
        ({"a": {"type": "guess", "instructions": "x"}}, "needs type noul, choice or score"),
        ({"a": {"type": "choice", "instructions": "x", "criteria": ["only"]}}, "at least two options"),
        ({"a": {"type": "score", "instructions": "x", "criteria": ["one"]}}, "needs between 2 and 10"),
        (
            {"a": {"type": "choice", "instructions": "x", "criteria": [str(i) for i in range(300)]}},
            "over the limit of 255",
        ),
        ("{not json", "does not parse"),
        ([], "empty"),
        ({f"q{i}": "x" for i in range(129)}, "over the ceiling of 128"),
    ]
    for questions, message in cases:
        result = await jev_ask(state="x", questions=questions, tool_context=_ctx(fake))
        assert result["status"] == "error", questions
        assert message in summary(result)
    assert fake.call_count == 0


async def test_ask_context_is_folded_next_to_the_state(fake: FakeJev) -> None:
    await jev_ask(state="draft", questions=["ok?"], context="the request", tool_context=_ctx(fake))
    assert fake.last_state == {"context": "the request", "subject": "draft"}


async def test_ask_reports_endpoint_failure_as_a_result() -> None:
    fake = FakeJev(error=TimeoutError("slow"))
    result = await jev_ask(state="x", questions=["ok?"], tool_context=_ctx(fake))
    assert result["status"] == "error"
    assert "Jev did not answer (TimeoutError: slow)" in summary(result)


async def test_ask_reports_missing_key_as_a_result(monkeypatch: Any, tmp_path: Any) -> None:
    from strands_jev import client as client_module

    monkeypatch.setattr(client_module, "KEY_FILE", tmp_path / "none")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    configure(None)
    result = await jev_ask(state="x", questions=["ok?"])
    assert result["status"] == "error"
    assert "Jev is not configured" in summary(result)


async def test_ask_rejects_an_invocation_state_endpoint_without_ask() -> None:
    class Ctx:
        invocation_state = {"jev": object()}

    result = await jev_ask(state="x", questions=["ok?"], tool_context=Ctx())
    assert result["status"] == "error"
    assert "must be a Jev" in summary(result)


async def test_configure_is_used_when_no_invocation_state(fake: FakeJev) -> None:
    configure(fake)
    try:
        result = await jev_ask(state="x", questions=["ok?"])
        assert result["status"] == "success" and fake.call_count == 1
    finally:
        configure(None)


async def test_models_and_usage_need_a_real_client(fake: FakeJev) -> None:
    result = await jev_models(tool_context=_ctx(fake))
    assert result["status"] == "error" and "does not list models" in summary(result)
    result = await jev_usage(tool_context=_ctx(fake))
    assert result["status"] == "error" and "no usage tally" in summary(result)


async def test_models_and_usage_with_a_jev_over_a_fake_sdk() -> None:
    class Listed:
        models = [{"name": "jev-latest", "description": "latest"}]

    class Models:
        async def list(self) -> Listed:
            return Listed()

    class Sdk:
        models = Models()

        async def system_one(self, *a: Any, **k: Any) -> Any:
            raise AssertionError("not called")

    jev = Jev(client=Sdk())  # type: ignore[arg-type]

    class Ctx:
        invocation_state = {"jev": jev}

    result = await jev_models(tool_context=Ctx())
    assert result["status"] == "success"
    assert summary(result) == "1 models: jev-latest"
    result = await jev_usage(tool_context=Ctx())
    assert payload(result)["calls"] == 0
    assert payload(result)["price_per_million_input_tokens_usd"] == 0.042


def test_direct_agent_call_reaches_the_tool_with_the_endpoint_from_invocation_state() -> None:
    """Through the SDK: ``agent.tool.jev_ask(...)`` injects ToolContext and accepts our result."""
    fake = FakeJev({"q1": noul(0.9)})
    agent = Agent(
        model=BedrockModel(model_id="never-called", region_name="us-east-1"), tools=ALL_TOOLS, callback_handler=None
    )
    result = agent.tool.jev_ask(state="evidence", questions=["is it evidence?"], jev=fake)
    assert fake.call_count == 1
    assert result["status"] == "success"
    assert result["toolUseId"].startswith("tooluse_jev_ask_")
    assert payload(result)["answers"]["q1"]["noul"] == 0.9


def test_helpers_refuse_rather_than_clamp() -> None:
    import pytest

    with pytest.raises(ValueError, match="got a boolean"):
        _common.fraction(True, "threshold", 0.5)
    with pytest.raises(ValueError, match="between 0 and 1"):
        _common.fraction(5, "threshold", 0.5)
    with pytest.raises(ValueError, match="between 1 and 10"):
        _common.whole(11, "top_k", 3, 1, 10)
    assert _common.fraction("", "t", 0.4) == 0.4
    assert _common.as_list("a\nb\n", "items") == ["a", "b"]
    assert _common.as_list('["a", 1]', "items") == ["a", 1]
    assert _common.as_mapping(["x", "y"], "options", None) == {"x": "x", "y": "y"}
    assert _common.as_mapping(["x", "y"], "props", "p") == {"p1": "x", "p2": "y"}
    assert _common.truncate("abcdef", 3).endswith("characters]")
