---
description: The tools in an agent, called directly and then chosen by the model.
---

# First agent

At the end of this page an agent has routed a support message with `route`, and a chat turn has let the model pick a Jev tool on its own.

## Hand over the tools

```python
from strands import Agent
from strands_jev import ALL_TOOLS

agent = Agent(tools=ALL_TOOLS)
```

`ALL_TOOLS` is every tool in the package, {{n:tools}} at this commit, in the three groups the [Tools reference](../tools/index.md) lists. Hand over a subset when the agent should only do one thing: `Agent(tools=[route, fan_out])`. Each tool resolves its endpoint in the same order: a `Jev` in `invocation_state["jev"]` on the call, then whatever `strands_jev.configure(...)` was given, then a `Jev()` built from the key on the machine.

## Route a request directly

```python
result = agent.tool.route(
    message="Third time writing. Webhooks silently drop every event since Tuesday and nobody answers.",
    intents={
        "bug_report": "something that used to work is broken",
        "billing": "charges, invoices, refunds, payouts",
        "complaint": "the writer is unhappy with how they were treated",
        "question": "the writer wants to know something",
    },
    handlers={"bug_report": "engineering", "billing": "finance", "complaint": "human", "question": "code"},
    complex_intents=["complaint"],
)
print(result["content"][1]["text"])
```

The request carries one Choice over the four intents plus `none_of_these` and a three-level complexity Score, in one call. The result has `intent`, `confidence`, `handler`, `escalate` and `reason`; the intent must clear `min_confidence` ({{n:confidence_floor}} by default) or its own entry in `thresholds`, and the intents in `complex_intents` also go to a person when the complexity score says so. Fourteen such messages routed 14/14 on {{n:live_date}} against a keyword baseline's 11/14; the page [Measured](../measured/index.md) has the rows.

## Let the model choose

```python
agent(
    "Here are two support messages. Which team should take each one, and which is more urgent?\n"
    "1. 'Charged twice this month, please refund one.'\n"
    "2. 'Since the update the export button does nothing.'"
)
```

The chat model reads the tool descriptions, which are the docstrings on the [Tools](../tools/index.md) pages, and calls `route` or `jev_ask` with questions it writes itself. It then answers in prose with Jev's numbers in hand. The default model for `Agent()` is Amazon Bedrock; any Strands model provider works, the Jev call is the same.

## Bring your own client

```python
from strands_jev import Jev

jev = Jev(model="jev-1.13.0")
agent = Agent(tools=ALL_TOOLS)
agent.tool.jev_usage(invocation_state={"jev": jev})
```

Passing a `Jev` in `invocation_state` pins the model id, lets you point at another `base_url`, and keeps the usage tally per client. `strands_jev.configure(jev)` does the same for every call in the process.
