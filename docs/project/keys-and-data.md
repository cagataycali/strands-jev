---
description: Where the key lives, what a request carries, and what TypeSafe keeps.
---

# Keys and data

## The key

`Jev()` reads `TYPESAFE_API_KEY`, then `~/.typesafe`. Nothing in the package writes a key, prints one, or includes one in an error message; a missing key raises `RuntimeError` naming the two places. The repository's `.gitignore` lists `.env`, `*.key` and `.typesafe`, and the live CI job reads the key from a repository secret that is never echoed.

Pass `Jev(api_key=...)` only when the key comes from your own secret store at runtime. Do not put it in code.

## What leaves the machine

One request is one HTTPS `POST` to `api.typesafe.ai/v1/systemone` carrying the `state`, the `instructions` and `criteria` of every question, and the model id. Question keys (`urgent`, `team`) stay on your side; the SDK maps answers back to them. Nothing else is sent: no conversation history, no tool results from earlier turns, no telemetry from this package.

The tools truncate a state longer than {{n:max_state_chars}} characters with a marker before sending, and the client refuses anything that would exceed the documented {{n:max_state_tokens}} or {{n:max_request_tokens}} token limits. What you pass as `state` is what the model reads; filter it to what the questions need, which is also what the [jaggedness guidance](../learn/what-not-to-ask.md) asks for.

## What TypeSafe keeps

TypeSafe documents its data handling and a zero data retention option on its own site: [docs.typesafe.ai](https://docs.typesafe.ai). Read that page for the terms that apply to your key; this package does not change them.

## Usage figures

The tally behind `jev_usage` is in-process memory: calls, questions, tokens, latency, and cost computed from the price constant. It is not written to disk and does not survive the process.
