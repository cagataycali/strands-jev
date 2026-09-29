---
description: What the whole live suite cost, and how to read the per-request numbers.
---

# Cost

The live suite on {{n:live_date}} made {{n:live_calls}} requests over {{n:live_tools}} tools and {{n:live_cases}} labelled cases: {{n:live_tokens}} input tokens, ${{n:live_cost}} at ${{n:price_per_mtok}} per million input tokens, output free. That is about {{n:live_cost_cents}} cents for every number on this site.

## Per request

Mean latency across the suite was {{n:live_mean_ms}} ms per request, measured on the client from a laptop, network included. Latency follows prompt length, not question count: many questions over one state cost about what one question costs, which is why every tool asks everything it needs in one request.

## Per tool

The `function_call` rows are the expensive ones on the table: 30 questions per command, so a 16-command run used more tokens than the other four tools together. That is the trade the cookbook makes on purpose, one request instead of a round trip per argument. The `composite_score` rows are the cheap ones, one request per item with three questions in it.

## Watching it

`jev_usage` reads the tally: calls, questions, input tokens, mean latency, cost so far. Every result also carries `input_tokens` and `latency_ms` for its own request. The price constant is `PRICE_PER_MILLION_INPUT_TOKENS` in `strands_jev/questions.py`; when TypeSafe changes the price, that one line changes and every cost on this site with it.
