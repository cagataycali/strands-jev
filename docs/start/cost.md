---
description: The price line, the budget check, and what the live suite cost.
---

# What it costs

At the end of this page you can read `jev_usage`, know which requests the package refuses before sending, and have the measured cost of everything on this site.

## The price

Jev bills input tokens only: ${{n:price_per_mtok}} per million, output free (docs.typesafe.ai/models, read {{n:live_date}}). The API reports token counts, not dollars, so the package computes cost from the price in `strands_jev/questions.py` and keeps a tally per client.

```python
from strands import Agent
from strands_jev import ALL_TOOLS

agent = Agent(tools=ALL_TOOLS)
agent.tool.jev_ask(state="Refund me.", questions={"angry": "Is the writer angry?"})
print(agent.tool.jev_usage()["content"][1]["text"])
```

The summary line reads calls, questions, input tokens, mean latency and cost so far. `reset=True` zeroes the counters after reading, for measuring one step at a time.

## The limits

Two documented limits (docs.typesafe.ai/api): {{n:max_request_tokens}} tokens per request, {{n:max_state_tokens}} for the state plus the longest single question. The client estimates tokens as characters divided by {{n:chars_per_token}} and refuses a request that cannot fit, before anything is sent:

```python
from strands_jev import BudgetExceeded, check_budget
from typesafe_sdk import Noul

try:
    check_budget("x" * 200_000, {"q": Noul(instructions="Is it long?")})
except BudgetExceeded as exc:
    print(exc)
```

`Jev.ask` runs the same check on every request, so a tool call that would exceed a limit comes back as `status: "error"` with this message and no bill.

The message names the estimated numbers and the fix: filter the state down, or split it into chunks and ask each chunk. The package adds two ceilings of its own, {{n:max_questions}} questions per request and {{n:max_items}} items per many-item call, as guards on the bill rather than documented API limits; both live in `questions.py`.

## What the live suite cost

Every number on [Measured](../measured/index.md) came from `hatch run live` on {{n:live_date}}: {{n:live_calls}} requests, {{n:live_tokens}} input tokens, ${{n:live_cost}} in total, about {{n:live_cost_cents}} cents. Mean latency {{n:live_mean_ms}} ms per request from a laptop, network included.

A request with a few hundred tokens of state and three questions is a few hundred tokens; at ${{n:price_per_mtok}} per million that is a few hundredths of a cent. The cost that matters is the one you can see: `jev_usage`, and the `input_tokens` field on every result.
