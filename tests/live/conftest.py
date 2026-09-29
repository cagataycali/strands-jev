"""Live suite plumbing: a real ``Jev``, a scoreboard, and the house rule on baselines.

Every live test compares Jev against the deterministic baseline a developer would write
without a model (keyword rules, lexical overlap, regexes). The test fails when the model
loses to the baseline, and it also fails when the baseline gets full marks: a case set the
baseline aces says nothing about the model, so the fix is to make the cases harder.

Each test records its cases, answers, latency, tokens and cost through ``board``. The
session writes ``tests/live/raw/<timestamp>.json`` (ignored by git) and the maintainer
folds the numbers into ``tests/live/RESULTS.md`` by hand.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from strands_jev import Jev
from strands_jev.client import KEY_FILE

RAW_DIR = Path(__file__).parent / "raw"


def _have_key() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY")) or KEY_FILE.expanduser().is_file()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _have_key():
        return
    skip = pytest.mark.skip(reason="no TypeSafe key: set TYPESAFE_API_KEY or write ~/.typesafe")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@dataclass
class Scorecard:
    """One tool's live result against its baseline."""

    tool: str
    cases: int
    model_correct: int
    baseline_correct: int
    calls: int
    input_tokens: int
    cost_usd: float
    latency_ms_mean: float
    model_id: str | None
    notes: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def model_score(self) -> float:
        return self.model_correct / self.cases if self.cases else 0.0

    @property
    def baseline_score(self) -> float:
        return self.baseline_correct / self.cases if self.cases else 0.0

    def check(self) -> None:
        """The house rule: the model must beat the baseline, and the baseline must not ace it."""
        assert self.cases > 0, f"{self.tool}: no cases"
        assert self.baseline_correct < self.cases, (
            f"{self.tool}: the baseline got {self.baseline_correct}/{self.cases}; make the cases harder"
        )
        assert self.model_correct > self.baseline_correct, (
            f"{self.tool}: Jev {self.model_correct}/{self.cases} did not beat the baseline "
            f"{self.baseline_correct}/{self.cases}"
        )


class Board:
    """Collects scorecards for the session and writes them as JSON at the end."""

    def __init__(self) -> None:
        self.cards: list[Scorecard] = []
        self.started = datetime.now(timezone.utc)

    def add(self, card: Scorecard) -> None:
        self.cards.append(card)

    def write(self) -> Path | None:
        if not self.cards:
            return None
        RAW_DIR.mkdir(exist_ok=True)
        path = RAW_DIR / f"{self.started.strftime('%Y%m%dT%H%M%SZ')}.json"
        payload = {
            "started": self.started.isoformat(),
            "cards": [
                {
                    **{key: value for key, value in card.__dict__.items() if key != "rows"},
                    "model_score": round(card.model_score, 3),
                    "baseline_score": round(card.baseline_score, 3),
                    "rows": card.rows,
                }
                for card in self.cards
            ],
            "total_cost_usd": round(sum(card.cost_usd for card in self.cards), 6),
            "total_input_tokens": sum(card.input_tokens for card in self.cards),
            "total_calls": sum(card.calls for card in self.cards),
        }
        path.write_text(json.dumps(payload, indent=2, default=str))
        return path


_BOARD = Board()


@pytest.fixture(scope="session")
def board() -> Board:
    return _BOARD


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    path = _BOARD.write()
    if path is not None:
        total = sum(card.cost_usd for card in _BOARD.cards)
        print(f"\nlive scoreboard: {len(_BOARD.cards)} cards, ${total:.6f}, written to {path}")


@pytest.fixture
def jev() -> Jev:
    """A fresh client per test so each scorecard's usage is its own."""
    return Jev(model="jev-latest")


class Ctx:
    """The slice of ToolContext the tools read."""

    def __init__(self, jev: Jev) -> None:
        self.invocation_state = {"jev": jev}


def card_from(jev: Jev, tool: str, rows: list[dict[str, Any]], notes: str = "") -> Scorecard:
    """Build a scorecard from the per-case rows (each with ``model_ok`` and ``baseline_ok``)."""
    usage = jev.usage
    return Scorecard(
        tool=tool,
        cases=len(rows),
        model_correct=sum(1 for row in rows if row["model_ok"]),
        baseline_correct=sum(1 for row in rows if row["baseline_ok"]),
        calls=usage.calls,
        input_tokens=usage.input_tokens,
        cost_usd=usage.cost_usd,
        latency_ms_mean=usage.latency_ms_mean,
        model_id=usage.last_model,
        notes=notes,
        rows=rows,
    )


def now_ms() -> float:
    return time.perf_counter() * 1000
