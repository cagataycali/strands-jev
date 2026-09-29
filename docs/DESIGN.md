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

The rest of the grid is filled in as each group lands.

## Folded and rejected

To be written as the groups land.

## Open questions

- The docs' Limits section gives token limits, not a question count. `MAX_QUESTIONS_PER_REQUEST`
  is 64 here as a guard on the bill, not a documented ceiling.
