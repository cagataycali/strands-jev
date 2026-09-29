---
description: Five ways to combine questions, each a tool in this package with the questions already written.
---

# Patterns

Follows the pattern pages under [docs.typesafe.ai/patterns](https://docs.typesafe.ai/patterns/fan-out) and the function-calling cookbook. Each pattern here is one tool; the [Tools reference](../tools/patterns.md) has the parameters.

## Fan-out

Questions in one request cannot see each other's answers, so a follow-up question is asked up front next to the question that decides whether it matters: "is this a bug report?" and "how severe is the bug?" travel together, and code keeps the severity only when the first answer says bug. Asking eight questions costs about what asking one costs, so the speculative ones are close to free. Tool: `fan_out`, where a premise is explicit data (`{"equals": ...}`, `{"at_least": ...}`) and skipped answers are returned under `skipped` rather than dropped. Measured: 10/12 tickets against a keyword baseline's 8/12.

## Confidence routing

Gate the decision on `confidence`, with a higher floor for the actions that hurt when wrong. Below the floor, escalate. Folded into `route` as `min_confidence` and per-intent `thresholds`; a separate tool would have been `route` with one intent.

## Intent routing

A Choice over your intents plus `none_of_these`, and a Score for how much judgement the request takes, in one request. The handler is a label your code dispatches on; anything undecided goes to a person. Tool: `route`. Measured: 14/14 messages against 11/14. One finding shaped the tool: gating complexity on every intent sent two clear lookups to a person, so `complex_intents` names where the gate applies, as the pattern does for complaints.

## Composite scoring

One Score per dimension, normalised to 0..1, combined under weights that live in code. Because the raw scores come back, a new weighting is a re-multiplication, not a re-inference. Tool: `composite_score`, which takes named `weights` profiles and ranks many items with one request each. Measured: 27/30 ordered pairs against 20/30.

## Function calling

Natural language to a function name and closed-set arguments: a Choice over the catalogue plus `none_of_these`, then per argument a Choice, a set of Nouls, a flag Noul and a "was this stated" Noul, all in one request (30 questions for a 7-function catalogue). Confidence is the minimum judgement, as the cookbook does. Tool: `function_call`, which takes the catalogue as input rather than reflecting Python signatures. Measured: 14/16 commands against 10/16, with one command sitting on the boundary between runs.

```python
r = agent.tool.fan_out(
    state="The app crashes every time I rotate my phone since Tuesday's update.",
    questions={
        "category": {"type": "choice", "instructions": "What kind of message is this?",
                     "criteria": {"bug": "something broke", "billing": "money", "feature": "a wish"}},
        "severity": {"type": "score", "instructions": "How bad is the impact?", "criteria": ["cosmetic", "degraded", "blocked"]},
        "refund": {"type": "noul", "instructions": "Does the writer want money back?"},
    },
    premises={"severity": {"question": "category", "equals": "bug"}, "refund": {"question": "category", "equals": "billing"}},
)
```

Every number above is from the {{n:live_date}} run on `{{n:live_model}}`; the rows and the misses are on [Measured](../measured/index.md).
