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

from typesafe_sdk import NoulCriteria

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

MAX_QUESTIONS_PER_REQUEST = 128
"""Ceiling this package puts on one fan-out. The API has no documented count limit; the token
limits above are the real bound. The function-calling cookbook sends 54 questions per command
(docs.typesafe.ai/cookbooks/function_calling); 128 leaves room and stops a runaway loop."""

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

DEFAULT_COMPLEXITY_ESCALATE_ABOVE = 1.0
"""Intent routing: a complexity score above this goes to a person (pattern used 1)."""

DEFAULT_COMPLEXITY_CONFIDENCE_FLOOR = 0.5
"""Intent routing: below this confidence on complexity, escalate (pattern used 0.5)."""

# --------------------------------------------------------------------------- questions
# Question text for tools that own a fixed question. Tools whose questions come from the
# caller (jev_ask, fan_out) have nothing here by design.

NO_MATCH = "none_of_these"
"""The option closed-set questions add so the model can say nothing fits."""

NO_MATCH_DESCRIPTION = "None of the listed options applies"

ROUTE_INTENT = "Which of these best describes what the message is asking for?"

ROUTE_COMPLEXITY = "How much judgement does resolving this request take?"
ROUTE_COMPLEXITY_LEVELS = [
    "A lookup or a fixed procedure answers it completely",
    "It needs some judgement or context but follows a known playbook",
    "It needs a person: an exception, a dispute, a policy call, or an angry customer",
]

FUNCTION_CHOICE = "What is the user asking to do? Pick the function that does it."

COMPOSITE_LEVELS = [
    "No evidence of this at all",
    "A mention or a hint, nothing substantial",
    "Some real evidence, at a basic level",
    "Strong evidence, clearly demonstrated",
    "Exceptional, among the strongest one would see",
]
"""Default rubric for composite_score dimensions when the caller gives none. Five levels,
index 0 first, normalised to 0..1 by dividing by 4 (composite-scoring pattern)."""

# ---------------------------------------------------------------- cookbook questions

RERANK_INSTRUCTIONS = "Does the candidate answer the query, as opposed to being merely on a similar topic?"
RERANK_CRITERIA: NoulCriteria = {
    "true": "The candidate states, establishes or directly answers what the query asks for",
    "false": "The candidate is only on a similar topic, or answers a different question",
}
"""cookbooks/rerank_typesafe: one Noul per query and candidate pair, sorted by probability."""

FIND_LINES_WHERE = 'Which line of the document contains the answer to: "{query}"?'
FIND_LINES_EXISTS = 'Does any line of the document address or answer: "{query}"?'
FIND_LINES_EXISTS_CRITERIA: NoulCriteria = {
    "true": "At least one line of the document states or directly implies the answer",
    "false": "No line of the document addresses this",
}
FIND_LINES_MAX_LINES = 255
"""cookbooks/line_search: Choice over line ids plus a presence Noul in one request. A Choice
takes at most 255 options, so longer documents are searched in windows."""

EXTRACT_VALUE_NONE = "none_of_these"
EXTRACT_VALUE_NONE_DESCRIPTION = "None of these is the requested value"
"""cookbooks/pre_parsed_value_extraction: the options are the candidate spans found in code, so
the choice is a verbatim copy of one of them; the model chooses, code owns the string."""

DATE_ABSENT = "The document does not state this, or it is not this kind of date."
DATE_MODE = (
    "How is {role} written? 'absolute' = a calendar date naming a month (e.g. 'August 14', 'the 3rd of "
    "March'); 'relative' = given relative to today (today, tomorrow, the day after tomorrow, or a named "
    "weekday such as 'next Thursday'); 'none' = the document does not state this date."
)
DATE_MONTH = "If {role} is an absolute calendar date, which month is it in?"
DATE_DAY = "If {role} is an absolute calendar date, which day of the month (1-31)?"
DATE_YEAR = (
    "If {role} is an absolute calendar date, which year? Pick 'none' if the document states no year "
    "(code infers it), or 'out_of_range' if a year is stated but not in the list."
)
DATE_DAY_ANCHOR = (
    "If {role} is relative to today, which day is it? 'today', 'tomorrow', 'day_after' (the day after "
    "tomorrow), or 'weekday' (a named day of the week)."
)
DATE_WEEKDAY = "If {role} names a day of the week, which one?"
DATE_WEEK_OFFSET = (
    "If {role} names a weekday, which week is it in? 'next' for 'next Thursday' or 'Thursday next week'; "
    "'current' for 'this Thursday'; 'none' for a bare weekday with no qualifier (just 'Thursday')."
)
DATE_YEAR_WINDOW = range(1990, 2041)
"""cookbooks/date_extraction: seven Choices read the shape and parts of a date; code assembles.
The cookbook lists 1900 to 2050; 51 years keeps the request smaller and covers what a
scheduling or invoicing document states. Out-of-range years are flagged, never guessed."""

DATE_CONFIDENCE_FLOOR = 0.6
"""cookbooks/date_extraction: below the lowest part confidence the date goes to review."""

CITATION_RELATION = "How does the section relate to the claim?"
CITATION_CRITERIA = {
    "supports": "The section states the claim or directly implies that it is true",
    "contradicts": "The section states the opposite of the claim or implies it is false",
    "says_nothing": "The section does not address what the claim asserts, either way",
}
CITATION_VERDICTS = {"supports": "verified", "contradicts": "contradicted", "says_nothing": "unsupported"}
CITATION_CONFIDENCE_FLOOR = 0.7
"""cookbooks/citation_check: a quote missing from the source is caught by string match first;
one Choice reads the quote's context against the claim. The cookbook says start high."""

COUNT_MATCHING = "Does this item satisfy: {condition}?"
"""model-jaggedness/jev-1.13: the model does not count, so one Noul per item and code counts."""
