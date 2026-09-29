---
description: How a live test is scored, what a baseline is, and the rule that keeps the cases honest.
---

# Method

Every row on [Live results](index.md) comes from one run of `hatch run live` against `api.typesafe.ai`, with the key on the machine and the model alias `jev-latest`. The versioned id that answered is recorded per row; it was `{{n:live_model}}` on {{n:live_date}}.

## What a case is

A case is one input with a label a person wrote before the run. A tool's answer counts only when every field the label covers matches: for `jev_ask` all three answers on a message, for `function_call` the function and every argument. Partial credit is not given, because an agent acting on the result gets no partial credit either.

## What a baseline is

The baseline for a tool is the deterministic code a developer would write for the same job without a model: keyword rules for urgency, vocabulary lookups for teams, keyword counts for resume scoring, keyword dispatch for function calling. It is written before the cases are read against it, and it runs on the same inputs in the same test.

## The house rule

A live test fails in two directions. It fails when Jev loses to its baseline, which is the obvious one. It also fails when the baseline gets full marks, because a case set that keyword rules ace measures nothing about the model. When that happened during the first runs, the fix was harder cases that defeat keywords (a bug phrased as a wish, a resume made of the right words and none of the substance, commands with no catalogue vocabulary), never a relabel toward the model's answer.

## What is recorded

Per case: the input, the label, Jev's answer, the baseline's answer, latency and input tokens. Per tool: cases, correct counts for both sides, calls, tokens, cost at ${{n:price_per_mtok}} per million input tokens, mean latency. The per-case records stay on the machine that ran the suite; the per-tool rows are the table on [Live results](index.md) and feed the numbers on every page of this site.

## Reading a miss

Misses are written up next to the table, not hidden. Some are label noise (a message a person called not urgent that Jev, and the baseline, called urgent). Some are the model's (severity one level high on two bug reports). Some sit on a boundary and flip between runs (one command in `function_call`); those are recorded as open questions in the [design note](../project/design.md), which is where a fix would start.
