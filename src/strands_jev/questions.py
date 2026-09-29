"""Every question, threshold and limit in this package, in one file.

The official TypeSafe skill asks for exactly this: the text the model reads and the numbers
the code branches on should be reviewable in one place, so a change of policy is a constant
edit under code review rather than a reworded prompt buried in a tool. Nothing in this file
talks to the network.

Sources for the limits and the price: docs.typesafe.ai/api and docs.typesafe.ai/models,
read 2026-09-29 against jev-1.13.0. Thresholds marked "cookbook" are the values the named
cookbook used; the docs say to treat them as starting points, not rules.
"""

from __future__ import annotations

# ------------------------------------------------------------------------------ limits

MAX_REQUEST_TOKENS = 64_000
"""Context per request (docs.typesafe.ai/api, Limits)."""

MAX_STATE_PLUS_QUESTION_TOKENS = 32_000
"""State plus the longest single question (docs.typesafe.ai/api, Limits)."""

MAX_CHOICE_OPTIONS = 255
"""Options per Choice question (docs.typesafe.ai/api, Choice)."""

MAX_SCORE_LEVELS = 10
"""Levels per Score question; at least 2 (docs.typesafe.ai/api, Score)."""

MIN_SCORE_LEVELS = 2

CHARS_PER_TOKEN = 4
"""The budget estimate divides characters by this. An estimate, not the billed count."""

PRICE_PER_MILLION_INPUT_TOKENS = 0.042
"""USD. Output tokens are free (docs.typesafe.ai/models, 2026-09-29)."""

MAX_QUESTIONS_PER_REQUEST = 64
"""Ceiling this package puts on one fan-out. The API has no documented count limit; the token
limits above are the real bound. 64 keeps a mistaken loop from sending a thousand."""

MAX_ITEMS_PER_BATCH = 500
"""Most items a many-item tool will judge in one call. A ceiling on the bill."""

MAX_CONCURRENCY = 8
"""Parallel requests in flight for the many-item tools. Rate limits are dynamic
(docs.typesafe.ai/api, 250k tokens per second, 1,200 requests per minute on 2026-09-29)."""

DEFAULT_MAX_STATE_CHARS = 12_000
"""Characters of state a tool sends before truncating with a marker. About 3k tokens."""

# -------------------------------------------------------------------------- thresholds

DEFAULT_CONFIDENCE_FLOOR = 0.6
"""Below this a Choice is a leaning, not a decision (confidence-routing pattern used 0.6)."""

DEFAULT_NOUL_THRESHOLD = 0.5
"""A Noul at or above this reads as yes."""

DEFAULT_UNCERTAIN_MARGIN = 0.15
"""Half-width of the band around a Noul threshold reported as uncertain instead of decided."""

# --------------------------------------------------------------------------- questions
# Question text for tools that own a fixed question. Tools whose questions come from the
# caller (jev_ask, fan_out, route) have nothing here by design.

PRESENCE_ABSENT = "not stated"
"""The option every closed-set question adds so the model can say nothing fits."""
