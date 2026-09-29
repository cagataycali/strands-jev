"""The client: key resolution, the budget check, the usage tally, loop-safe client rebuild."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from typesafe_sdk import Choice, Noul, NoulAnswer, Score

from strands_jev import BudgetExceeded, Jev, check_budget, estimate_tokens
from strands_jev import client as client_module
from strands_jev.questions import MAX_REQUEST_TOKENS, MAX_STATE_PLUS_QUESTION_TOKENS, PRICE_PER_MILLION_INPUT_TOKENS


def test_estimate_tokens_is_chars_over_four() -> None:
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens({"k": "v"}) == max(1, len('{"k": "v"}') // 4)


def test_budget_refuses_state_plus_question_over_32k() -> None:
    state = "x" * (MAX_STATE_PLUS_QUESTION_TOKENS * 4 + 400)
    with pytest.raises(BudgetExceeded, match="32000 token limit for state plus one question"):
        check_budget(state, {"q": Noul(instructions="short")})


def test_budget_refuses_total_over_64k() -> None:
    state = "x" * (30_000 * 4)
    long_q = Noul(instructions="y" * (1_000 * 4))
    questions = {f"q{i}": long_q for i in range(40)}
    with pytest.raises(BudgetExceeded, match=f"over the {MAX_REQUEST_TOKENS} token limit per request"):
        check_budget(state, questions)


def test_budget_passes_and_reports_estimate() -> None:
    estimate = check_budget("hello world", {"a": Noul(instructions="is it a greeting?")})
    assert estimate["state_tokens"] == 2
    assert estimate["total_tokens"] > estimate["state_tokens"]


def test_read_key_prefers_argument_then_env_then_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client_module, "KEY_FILE", tmp_path / ".typesafe")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="set TYPESAFE_API_KEY"):
        client_module.read_key()
    (tmp_path / ".typesafe").write_text("file-key\n")
    assert client_module.read_key() == "file-key"
    monkeypatch.setenv("TYPESAFE_API_KEY", "env-key")
    assert client_module.read_key() == "env-key"
    assert client_module.read_key("arg-key") == "arg-key"


class _FakeResponse:
    def __init__(self, answers: dict[str, Any], tokens: int) -> None:
        self.model = "jev-1.13.0"
        self.answers = answers

        class Usage:
            input_tokens = tokens
            output_tokens = 0

        self.usage = Usage()


class _FakeSdkClient:
    def __init__(self) -> None:
        self.calls = 0

    async def system_one(self, state: Any, questions: Any, *, model: str | None = None, **_: Any) -> _FakeResponse:
        self.calls += 1
        return _FakeResponse({key: NoulAnswer(noul=0.9) for key in questions}, tokens=1000)

    async def aclose(self) -> None:
        pass


async def test_ask_tallies_tokens_cost_and_latency() -> None:
    sdk = _FakeSdkClient()
    jev = Jev(client=sdk)  # type: ignore[arg-type]
    answers = await jev.ask("state", {"a": Noul(instructions="a"), "b": Noul(instructions="b")})
    assert answers["a"].noul == 0.9
    usage = jev.usage
    assert usage.calls == 1 and usage.questions == 2 and usage.input_tokens == 1000
    assert usage.cost_usd == pytest.approx(1000 / 1_000_000 * PRICE_PER_MILLION_INPUT_TOKENS)
    assert usage.last_model == "jev-1.13.0"
    assert usage.latency_ms_total >= 0
    assert "2 questions" in str(usage)
    jev.reset_usage()
    assert jev.usage.calls == 0


async def test_ask_refuses_over_budget_before_calling_the_sdk() -> None:
    sdk = _FakeSdkClient()
    jev = Jev(client=sdk)  # type: ignore[arg-type]
    with pytest.raises(BudgetExceeded):
        await jev.ask("x" * 200_000, {"a": Noul(instructions="a")})
    assert sdk.calls == 0


def test_client_is_rebuilt_when_the_event_loop_changes() -> None:
    jev = Jev(api_key="k")
    first = asyncio.run(_get_client(jev))
    second = asyncio.run(_get_client(jev))
    assert first is not second
    assert repr(jev) == "Jev(model='jev-latest', base_url='https://api.typesafe.ai')"


async def _get_client(jev: Jev) -> Any:
    return jev._ensure_client()


def test_missing_key_raises_at_construction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client_module, "KEY_FILE", tmp_path / "none")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="no TypeSafe API key"):
        Jev()


def test_sdk_question_types_round_trip_through_budget() -> None:
    questions = {
        "c": Choice(instructions="which?", criteria={"a": None, "b": "second"}),
        "s": Score(instructions="how much?", criteria=["low", "high"]),
    }
    assert check_budget("s", questions)["longest_question_tokens"] >= 1
