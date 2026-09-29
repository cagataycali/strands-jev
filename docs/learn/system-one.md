---
description: One state, typed questions, typed answers with probabilities, one forward pass, no generated text.
---

# System One

Follows [docs.typesafe.ai/concepts/system-one](https://docs.typesafe.ai/concepts/system-one).

A System One model evaluates a **state** against one or more typed **questions** and returns a typed **answer** per question, with probabilities. It understands natural language on the way in. It does not write replies, code or explanations on the way out: you define every possible answer before you ask. Jev is TypeSafe's flagship model and the first of the class. The name is Kahneman's: fast, focused judgement, not deliberation.

## Why an agent wants one

A chat model in a Strands agent is good at proposing: reading the situation, drafting, choosing a tool. It is inconsistent at judging: the same message read twice gets two urgencies, and the number it writes down is not a probability of anything. Jev is the opposite. It only judges, it does so the same way every time, and its probabilities are trained against outcomes, so a 0.9 means something across many calls (calibration is a property of groups of predictions, the docs say, not a guarantee on one).

So the division of labour in this package: the agent proposes, Jev decides, code acts on the number.

## One request

```python
from strands import Agent
from strands_jev import ALL_TOOLS

agent = Agent(tools=ALL_TOOLS)
r = agent.tool.jev_ask(
    state={"message": "I was charged twice for order A-104. Please refund the duplicate.",
           "charges": [{"amount_usd": 49}, {"amount_usd": 49}],
           "refund_policy": "Duplicate charges are eligible for a refund."},
    questions={
        "asks_refund": "Does the customer ask for a refund?",
        "duplicate": "Do the charges show the same amount captured twice?",
        "policy_allows": "Does the refund policy cover this case?",
    },
)
print(r["content"][1]["text"])
```

Three yes/no questions over one state, one HTTP call. Every question sees the same state and none sees another's answer. Code then combines the three probabilities with its own checks (is the order real, is the customer who they say they are) and routes the case. That is the workflow the docs describe: build the state, ask everything at once, decide in code.

## What it is not

Not a chat model: nothing is generated. Not a classifier you train: the answer space is in the request. Not a reasoner: it reads literally, and the [jaggedness page](what-not-to-ask.md) is the list of what that costs. Text only at jev-1.13; English first.
