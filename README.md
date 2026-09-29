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

More groups (patterns, cookbooks) are on the way; see `docs/DESIGN.md`.

## Measured

From `tests/live/RESULTS.md`, 2026-09-29, jev-1.13.0:

| tool | Jev | baseline | mean latency | cost |
| --- | --- | --- | --- | --- |
| `jev_ask`, 8 tickets x 3 questions | 7/8 | 5/8 (keyword rules) | 179 ms | $0.000148 for 8 calls |

## What not to ask

From the jaggedness page for Jev 1.13 (docs.typesafe.ai/model-jaggedness/jev-1.13): Jev
reads literally. It does not count or do arithmetic (count in code, one noul per item), it
does not compare dates (extract parts as a Choice, compare in code), indirection hurts,
large irrelevant state hurts (filter first), adversarial content in the state moves
answers, and it cannot generate anything.

## Key handling

The key is read from `TYPESAFE_API_KEY`, then from `~/.typesafe`. It is never written by
this package. `.env`, `*.key` and `.typesafe` are ignored by git.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
hatch run prepare        # format, lint, typecheck, unit tests
hatch run live           # the live suite; needs the key and spends money
```
