# Design

## What this is

Tools for a Strands agent to call Jev, TypeSafe's System One model. Jev answers typed
questions (Noul, Choice, Score) about one state in one forward pass and returns
probabilities. It does not generate text. The API is two routes, `POST /v1/systemone` and
`GET /v1/models` (docs.typesafe.ai/api), so "all of Jev" means the three primitives, the
structured instructions and criteria, the fan-out of many questions over one state, and
the patterns and cookbooks built from them.

This repo is separate from `strands-decisions`, which puts a decision model behind the
agent as intervention handlers. Here the agent is in front: it decides to ask.

## Layout

- `strands_jev/client.py`: `Jev`, the client. Key from `TYPESAFE_API_KEY` or `~/.typesafe`.
  Budget check before sending (64k per request, 32k state plus longest question). Usage
  tally with cost computed at $0.042 per million input tokens. Client rebuilt when the
  event loop changes.
- `strands_jev/questions.py`: every limit, threshold and fixed question text, in one file.
- `strands_jev/tools/_common.py`: endpoint resolution (`invocation_state["jev"]`, then
  `configure()`, then `Jev()`), input tolerance, refusals, result shape.
- `strands_jev/tools/<group>.py`: one module per group.

## Tools against the docs

| tool | group | docs page ported | how it differs |
| --- | --- | --- | --- |
| jev_ask | primitives | api, primitives, primitives/noul, primitives/choice, primitives/score, primitives#advanced-structure | dict specs instead of SDK objects; a bare string is a noul; a list is named q1..qN |
| jev_models | primitives | models | returns the raw rows |
| jev_usage | primitives | models (price) | cost computed, the API reports tokens only |
| fan_out | patterns | patterns/fan-out | premises are explicit data (`equals`, `at_least`), skipped answers are returned, not dropped |
| route | patterns | patterns/intent-routing, patterns/confidence-routing | one tool: intent Choice + complexity Score, per-intent thresholds, `complex_intents` names where the complexity gate applies, `none_of_these` added |
| composite_score | patterns | patterns/composite-scoring | weight profiles validated in code, raw normalised scores returned, `items` ranks many with one request each |
| function_call | patterns | cookbooks/function_calling | the spec is the tool input (no signature reflection), `none_of_these` on the function Choice, confidence is the minimum judgement as in the cookbook |

## Folded and rejected

- confidence-gated routing is folded into `route` as `thresholds` (per-intent floors). A
  separate tool would have been `route` with one intent.
- `route` gates complexity only on `complex_intents`. Measured 2026-09-29: gating every
  intent escalated two clear lookups because a 3-level Score's confidence sat at 0.42 and
  0.43, under the pattern's 0.5 floor. The pattern itself gates only complaints.
- `function_call` does not read Python signatures the way the cookbook's `closed_sets`
  does. The agent hands over a catalogue; a signature reader is one function on top and
  would tie the tool to Python callables.

## Open questions

- `function_call` on "show me apple daily with volume" returned `plot_price` with all three
  arguments in one run and `none_of_these` at 0.45 in the next. The function Choice sits
  near the boundary for that command; a `stated` question on the whole request or a second
  request over the top two functions might settle it. Not done yet.
- The docs' Limits section gives token limits, not a question count. `MAX_QUESTIONS_PER_REQUEST`
  is 64 here as a guard on the bill, not a documented ceiling.
