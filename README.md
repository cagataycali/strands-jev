# strands-jev

Strands Agents tools around Jev, TypeSafe's System One decision model.

Jev reads one piece of state and a set of typed questions and returns typed answers with
probabilities in one forward pass: a Noul is a yes/no question and returns the probability
of yes; a Choice picks one option from a set you define and returns the option, a
confidence and every option's probability; a Score rates the state on an ordered scale you
describe and returns a probability-weighted position. It does not generate text. Many
questions about the same state are answered in parallel in one request, so asking eight
costs about what asking one costs (docs.typesafe.ai/primitives).

These tools let a Strands agent use that. A chat model proposes; Jev judges, consistently,
with a calibrated number, for a fraction of a cent. The raw call is one tool (`jev_ask`);
the patterns and cookbooks from the TypeSafe docs are the rest, each with its questions
already written and its thresholds in one reviewable module.

## Quick start

```bash
pip install git+https://github.com/cagataycali/strands-jev
echo "<your key>" > ~/.typesafe && chmod 600 ~/.typesafe   # or export TYPESAFE_API_KEY=...
```

```python
from strands import Agent
from strands_jev import ALL_TOOLS

agent = Agent(tools=ALL_TOOLS)
agent("Is this ticket urgent, and which team should take it? 'Help! My payouts have been failing for 3 days.'")
```

Or call a tool directly, no chat model involved:

```python
result = agent.tool.jev_ask(
    state="Help! My payouts have been failing for 3 days.",
    questions={
        "urgent": {"type": "noul", "instructions": "Does this convey urgency?"},
        "team": {"type": "choice", "instructions": "Which team?", "criteria": {"billing": "payments", "technical": "bugs"}},
    },
)
```

## Tools

| tool | what it does |
| --- | --- |
| `jev_ask` | The raw call: one state, any mix of noul, choice and score questions, one request. |
| `jev_models` | The model ids the endpoint serves. |
| `jev_usage` | Calls, tokens, latency and computed cost so far. |
| `fan_out` | Every question in one request, speculative ones tied to a premise; applicable answers kept, the rest reported as skipped. |
| `route` | Intent Choice plus complexity Score; confidence floor, per-intent thresholds, a person as the default handler. |
| `composite_score` | Atomic Score per dimension, normalised, combined under weight profiles in code; ranks items. |
| `function_call` | Request to function name plus closed-set arguments with per-argument confidence and a no-match outcome. |
| `rerank` | One Noul per query and candidate pair, in parallel, best first. Fast search stays yours. |
| `find_lines` | Which numbered line answers each query, plus whether any line does, in one request per query. |
| `extract_value` | Pick one of the spans code already found (emails, amounts, dates); the value is a verbatim copy. |
| `extract_date` | Seven Choices read the shape and parts of a date; code assembles it and reports the weakest confidence. |
| `verify_citations` | Missing quotes fail by string match; present ones get supports, contradicts or says nothing. |
| `count_matching` | One Noul per item, the count done in code, because Jev does not count. |
| `align_entities` | Same, related or different for record pairs: a 3-level Score plus a Noul per field saying where they disagree. |
| `classify_hierarchical` | One Choice per taxonomy level, descending while confident, with none_of_these at every level. |
| `recover_structure` | Flattened text back to Markdown: stitch torn lines, then type each block (heading, step, quote, code, callout). |
| `guardrail` | The cookbook's hazard batteries (input or output) plus a severity Score; your policy decides. |
| `pick_from_catalog` | Rank a catalogue of up to 255 entries in one request, re-check the top k in a second, pick one or none. |
| `consistency_check` | Ask, optionally repeat, report agreement, and route anything near a threshold to review. |

`docs/DESIGN.md` maps every tool to the docs page it ports and says what was folded or left out.

## Measured

From `tests/live/RESULTS.md`, 2026-09-29, jev-1.13.0:

| tool | Jev | baseline | mean latency | cost |
| --- | --- | --- | --- | --- |
| `jev_ask`, 8 tickets x 3 questions | 7/8 | 5/8 (keyword rules) | 179 ms | $0.000148 for 8 calls |
| `fan_out`, 12 tickets x 4 questions | 10/12 | 8/12 (keyword rules) | 159 ms | $0.000231 for 12 calls |
| `route`, 14 messages | 14/14 | 11/14 (keyword rules) | 179 ms | $0.000289 for 14 calls |
| `composite_score`, 30 resume pairs | 27/30 | 20/30 (keyword counts) | 213 ms | $0.000139 for 6 calls |
| `function_call`, 16 commands | 14/16 | 10/16 (keyword dispatch) | 172 ms | $0.001253 for 16 calls |
| `rerank`, 6 queries x 8 passages | 6/6 | 0/6 (token overlap) | 178 ms | $0.000745 for 48 calls |
| `find_lines`, 8 queries, 21 lines | 7/8 | 2/8 (word overlap) | 158 ms | $0.000284 for 8 calls |
| `extract_value`, 8 documents | 8/8 | 2/8 (first span) | 162 ms | $0.000131 for 8 calls |
| `extract_date`, 8 documents | 8/8 | 5/8 (regex) | 144 ms | $0.000562 for 8 calls |
| `verify_citations`, 10 citations | 8/10 | 5/10 (string match) | 216 ms | $0.000182 for 9 calls |
| `count_matching`, 12 log lines | 11/12 | 9/12 (grep) | 184 ms | $0.000160 for 12 calls |
| `align_entities`, 8 record pairs | 8/8 | 5/8 (name overlap) | 233 ms | $0.000165 for 8 calls |
| `classify_hierarchical`, 12 tickets | 11/12 | 8/12 (keyword paths) | 158 ms | $0.000342 for 22 calls |
| `recover_structure`, 11 blocks | 10/11 | 0/11 (punctuation rules) | 157 ms | $0.000293 for 2 calls |
| `guardrail`, 10 messages | 10/10 | 9/10 (keyword filter) | 152 ms | $0.000269 for 10 calls |
| `pick_from_catalog`, 8 requests | 7/8 | 3/8 (token overlap) | 160 ms | $0.000436 for 16 calls |
| `consistency_check`, 3 questions x 3 | 3/3 | 2/3 (keywords) | 244 ms | $0.000048 for 3 calls |

Everything above cost $0.0057 in total over 213 calls. Every tool beat the code a developer would write without a model, on case sets written so that code could not ace them.

## What not to ask

From the jaggedness page for Jev 1.13 (docs.typesafe.ai/model-jaggedness/jev-1.13): Jev
reads literally. It does not count or do arithmetic (count in code, one noul per item), it
does not compare dates (extract parts as a Choice, compare in code), indirection hurts,
large irrelevant state hurts (filter first), adversarial content in the state moves
answers, and it cannot generate anything.

## Key handling and the endpoint

The key is read from `TYPESAFE_API_KEY`, then from `~/.typesafe`. It is never written by
this package. `.env`, `*.key` and `.typesafe` are ignored by git.

Which client answers a tool call, in order: `invocation_state["jev"]` (per call, so one
agent can serve several keys or a test double), `strands_jev.configure(Jev(...))` (once at
startup), then a `Jev()` built from the key on the machine. `Jev` refuses a request before
sending it when the estimate exceeds the documented limits (64k tokens per request, 32k for
state plus the longest question), keeps a tally of calls, tokens and latency, and computes
the cost at $0.042 per million input tokens because the API reports tokens only.

Tool groups: `PRIMITIVE_TOOLS`, `PATTERN_TOOLS`, `COOKBOOK_TOOLS`, `COOKBOOK_TOOLS_2`, and
`ALL_TOOLS` for all 19. Every question, threshold and limit lives in `strands_jev/questions.py`
so it can be reviewed in one place.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
hatch run prepare        # format, lint, typecheck, unit tests
hatch run live           # the live suite; needs the key and spends money
```
