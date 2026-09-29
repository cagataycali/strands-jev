"""``Jev``: the one client every tool in this package talks through.

Jev is TypeSafe's System One model. It reads one ``state`` and a map of typed questions
(Noul, Choice, Score) and returns one typed answer per question with probabilities, in one
forward pass. It does not generate text. The whole API is two routes, ``POST /v1/systemone``
and ``GET /v1/models`` (docs.typesafe.ai/api), and this class wraps the official
``typesafe-sdk`` ``AsyncTypeSafeClient`` for both.

What the wrapper adds:

- key resolution: ``TYPESAFE_API_KEY``, then the file ``~/.typesafe``;
- a request budget check before anything is sent, against the documented limits
  (64k tokens per request, 32k for state plus the longest question; docs.typesafe.ai/api);
- a running tally of calls, tokens, latency and cost. The API reports tokens only, so cost
  is computed here at $0.042 per million input tokens (docs.typesafe.ai/models, 2026-09-29);
- a client that is rebuilt when the event loop changes, so one ``Jev`` survives
  ``asyncio.run()`` being called more than once.

Tests hand the tools a ``FakeJev`` with the same ``ask`` signature; see ``JevEndpoint``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from typesafe_sdk import Answer, AsyncTypeSafeClient, Question, RetryPolicy

from .questions import (
    CHARS_PER_TOKEN,
    MAX_REQUEST_TOKENS,
    MAX_STATE_PLUS_QUESTION_TOKENS,
    PRICE_PER_MILLION_INPUT_TOKENS,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
"""An alias that follows new Jev releases. ``last_model`` reports the version that answered."""

DEFAULT_TIMEOUT = 30.0
"""Seconds per request. A 13-question request over a 3k-token article answered in 0.6 s in the
parallel-questions cookbook; 30 s leaves room for retries on a slow day."""

KEY_ENV = "TYPESAFE_API_KEY"
KEY_FILE = Path("~/.typesafe")


class JevEndpoint(Protocol):
    """Anything a tool in this package can ask a question of. Structural, so a fake works."""

    async def ask(self, state: Any, questions: Mapping[str, Question]) -> Mapping[str, Answer]:
        """Evaluate ``state`` against ``questions``; one answer per key."""
        ...


@dataclass(frozen=True)
class JevUsage:
    """What the calls so far have cost.

    Attributes:
        calls: Requests that returned answers. Failed requests are not counted.
        questions: Questions asked across those calls.
        input_tokens: Input tokens billed, as reported by the API.
        output_tokens: Output tokens, as reported. Free on the hosted model.
        cost_usd: ``input_tokens`` times the published price. Computed, not reported.
        latency_ms_total: Wall-clock milliseconds spent waiting for answers.
        last_model: The versioned model id that answered most recently, or ``None``.
    """

    calls: int
    questions: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms_total: float
    last_model: str | None

    @property
    def latency_ms_mean(self) -> float:
        """Mean latency per call, or 0.0 when nothing has been asked."""
        return self.latency_ms_total / self.calls if self.calls else 0.0

    def as_dict(self) -> dict[str, Any]:
        """A JSON-ready view, rounded for reading."""
        return {
            "calls": self.calls,
            "questions": self.questions,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms_mean": round(self.latency_ms_mean, 1),
            "latency_ms_total": round(self.latency_ms_total, 1),
            "last_model": self.last_model,
            "price_per_million_input_tokens_usd": PRICE_PER_MILLION_INPUT_TOKENS,
        }

    def __str__(self) -> str:
        return (
            f"{self.calls} calls, {self.questions} questions, {self.input_tokens} input tokens, "
            f"${self.cost_usd:.6f}, {self.latency_ms_mean:.0f} ms mean"
        )


class BudgetExceeded(ValueError):
    """A request would exceed a documented limit. Raised before anything is sent."""


def estimate_tokens(value: Any) -> int:
    """Approximate the tokens ``value`` will cost, as characters divided by 4.

    The API bills real tokens; this is only for refusing requests that cannot fit. Four
    characters per token is the SDK's own rule of thumb for English text.
    """
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return max(1, len(text) // CHARS_PER_TOKEN)


def check_budget(state: Any, questions: Mapping[str, Any]) -> dict[str, int]:
    """Refuse a request that cannot fit the documented context.

    Args:
        state: What the model will read.
        questions: The question map, SDK objects or plain dicts.

    Returns:
        The estimate: ``state_tokens``, ``longest_question_tokens``, ``total_tokens``.

    Raises:
        BudgetExceeded: State plus the longest question is over 32k tokens, or the whole
            request is over 64k. The message names the numbers and the fix.
    """
    state_tokens = estimate_tokens(state)
    question_tokens = [estimate_tokens(_question_payload(question)) for question in questions.values()]
    longest = max(question_tokens, default=0)
    total = state_tokens + sum(question_tokens)
    estimate = {"state_tokens": state_tokens, "longest_question_tokens": longest, "total_tokens": total}
    if state_tokens + longest > MAX_STATE_PLUS_QUESTION_TOKENS:
        raise BudgetExceeded(
            f"state ({state_tokens} tokens, estimated) plus the longest question ({longest}) is over the "
            f"{MAX_STATE_PLUS_QUESTION_TOKENS} token limit for state plus one question. Filter the state down "
            "to what the questions need, or split it into chunks and ask each chunk."
        )
    if total > MAX_REQUEST_TOKENS:
        raise BudgetExceeded(
            f"the request is {total} tokens (estimated), over the {MAX_REQUEST_TOKENS} token limit per request. "
            f"Send fewer questions per request ({len(questions)} now) or a smaller state."
        )
    return estimate


def _question_payload(question: Any) -> Any:
    if hasattr(question, "model_dump"):
        return question.model_dump(exclude_none=True)
    return question


def read_key(api_key: str | None = None) -> str:
    """Resolve the API key: the argument, ``TYPESAFE_API_KEY``, then ``~/.typesafe``.

    Raises:
        RuntimeError: No key anywhere. The message says where to put one.
    """
    if api_key:
        return api_key
    from_env = os.environ.get(KEY_ENV)
    if from_env:
        return from_env.strip()
    path = KEY_FILE.expanduser()
    if path.is_file():
        text = path.read_text().strip()
        if text:
            return text
    raise RuntimeError(
        f"no TypeSafe API key: set {KEY_ENV}, or write the key to {KEY_FILE} (chmod 600), or pass api_key= to Jev()."
    )


class Jev:
    """The Jev endpoint with a budget check and a usage tally.

    Example:
        ```python
        from typesafe_sdk import Noul
        from strands_jev import Jev

        jev = Jev()
        answers = await jev.ask("Help! My payouts have been failing for 3 days.", {"urgent": Noul("Is it urgent?")})
        print(answers["urgent"].noul, jev.usage)
        ```
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry: RetryPolicy | None = None,
        headers: Mapping[str, str] | None = None,
        client: AsyncTypeSafeClient | None = None,
    ) -> None:
        """Build the endpoint. The key is resolved now; the HTTP client on first use.

        Args:
            api_key: Overrides ``TYPESAFE_API_KEY`` and ``~/.typesafe``.
            model: Model id sent with every request. ``jev-latest`` by default; pin
                ``jev-1.13.0`` if thresholds were tuned against it.
            base_url: Endpoint root; the SDK appends ``/v1/systemone``. Honours
                ``TYPESAFE_BASE_URL`` when unset.
            timeout: Seconds per request.
            retry: SDK retry policy. The default retries 429 and 5xx with backoff.
            headers: Extra headers on every request.
            client: A ready ``AsyncTypeSafeClient``; then the other connection arguments are
                ignored and closing it stays with the caller.

        Raises:
            RuntimeError: No API key could be found.
        """
        self.model = model
        self.base_url = base_url or os.environ.get("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL
        self._timeout = timeout
        self._retry = retry
        self._headers = dict(headers) if headers else None
        self._client = client
        self._owns_client = client is None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._api_key = None if client is not None else read_key(api_key)

        self._calls = 0
        self._questions = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._latency_ms = 0.0
        self.last_model: str | None = None
        self.last_latency_ms: float = 0.0
        self.last_input_tokens: int = 0

    # ---------------------------------------------------------------------------- usage

    @property
    def usage(self) -> JevUsage:
        """A snapshot of calls, tokens, latency and computed cost so far."""
        return JevUsage(
            calls=self._calls,
            questions=self._questions,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cost_usd=self._input_tokens / 1_000_000 * PRICE_PER_MILLION_INPUT_TOKENS,
            latency_ms_total=self._latency_ms,
            last_model=self.last_model,
        )

    def reset_usage(self) -> None:
        """Zero the counters, for measuring one step at a time."""
        self._calls = 0
        self._questions = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._latency_ms = 0.0

    # ------------------------------------------------------------------------- the call

    async def ask(
        self, state: Any, questions: Mapping[str, Question], *, model: str | None = None
    ) -> Mapping[str, Answer]:
        """Evaluate ``state`` against ``questions`` in one request.

        Args:
            state: Text, or a JSON-serialisable object whose field names carry meaning.
            questions: Named ``Noul``, ``Choice`` or ``Score`` questions. Keys come back as
                answer keys and are not shown to the model.
            model: Override the model id for this call.

        Returns:
            One answer per question, under the same keys.

        Raises:
            BudgetExceeded: The request cannot fit the documented context.
            TypeSafeAPIError: The endpoint answered with an error after retries.
        """
        check_budget(state, questions)
        client = self._ensure_client()
        started = time.perf_counter()
        response = await client.system_one(state, questions, model=model or self.model)
        elapsed_ms = (time.perf_counter() - started) * 1000

        self._calls += 1
        self._questions += len(questions)
        self._latency_ms += elapsed_ms
        self.last_latency_ms = elapsed_ms
        self.last_model = getattr(response, "model", None) or None
        usage = getattr(response, "usage", None)
        self.last_input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        self._input_tokens += self.last_input_tokens
        self._output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        logger.debug(
            "model=<%s>, questions=<%d>, input_tokens=<%d>, latency_ms=<%.0f> | jev",
            self.last_model,
            len(questions),
            self.last_input_tokens,
            elapsed_ms,
        )
        return dict(response.answers)

    async def models(self) -> list[dict[str, Any]]:
        """``GET /v1/models``: the ids and aliases the endpoint serves."""
        client = self._ensure_client()
        listed = await client.models.list()
        rows: list[dict[str, Any]] = []
        for item in getattr(listed, "models", None) or getattr(listed, "data", None) or []:
            if hasattr(item, "model_dump"):
                rows.append(item.model_dump(exclude_none=True))
            else:
                rows.append(dict(item))
        return rows

    def _ensure_client(self) -> AsyncTypeSafeClient:
        """Build the HTTP client on first use and rebuild it when the event loop changed.

        An async HTTP client belongs to the loop that opened its connections; reusing it
        from a second ``asyncio.run()`` raises ``Event loop is closed``. One ``Jev`` used by
        a CLI that runs an agent twice, or by a test suite, is the normal case, so the
        client is tracked against its loop and replaced instead.
        """
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._client is not None and self._owns_client and loop is not None and self._client_loop is not loop:
            self._client = None
        if self._client is None:
            self._client = AsyncTypeSafeClient(
                api_key=self._api_key,
                base_url=self.base_url,
                model=self.model,
                timeout=self._timeout,
                retry=self._retry,
                headers=self._headers,
            )
            self._client_loop = loop
        return self._client

    async def aclose(self) -> None:
        """Close the HTTP client, unless the caller supplied it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
            self._client_loop = None

    async def __aenter__(self) -> Jev:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"Jev(model={self.model!r}, base_url={self.base_url!r})"
