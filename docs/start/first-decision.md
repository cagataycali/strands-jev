---
description: One request, three typed answers, and what every field in them means.
---

# First decision

At the end of this page you have asked Jev a yes/no question, a pick-one question and a rate-it question about the same sentence, in one request, and you can read the answer without guessing.

## The call

`jev_ask` is the raw API as a tool. A Strands `Agent` exposes every tool for direct calls under `agent.tool.<name>`, no chat model involved, so the whole thing is one Python call:

```python
from strands import Agent
from strands_jev import ALL_TOOLS

agent = Agent(tools=ALL_TOOLS)
result = agent.tool.jev_ask(
    state="Help! My payouts have been failing for 3 days.",
    questions={
        "urgent": {"type": "noul", "instructions": "Does this convey urgency?"},
        "team": {
            "type": "choice",
            "instructions": "Which team should take this?",
            "criteria": {"billing": "payments, charges, payouts", "technical": "bugs and outages", "sales": "plans and pricing"},
        },
        "frustration": {
            "type": "score",
            "instructions": "How frustrated is the writer?",
            "criteria": ["calm", "frustrated", "very angry"],
        },
    },
)
print(result["content"][1]["text"])
answers = result["content"][0]["json"]["answers"]
```

The second content block is a one-line summary for a model to read; the first is the JSON. One recorded run of this exact request on {{n:live_date}} came back in 178 ms for 434 input tokens, which is $0.000018 at ${{n:price_per_mtok}} per million.

## Reading the answers

```json
{
  "urgent": {"type": "noul", "noul": 0.95},
  "team": {"type": "choice", "choice": "billing", "confidence": 0.98,
           "probabilities": {"billing": 0.99, "technical": 0.01, "sales": 0.0}},
  "frustration": {"type": "score", "score": 1.04, "confidence": 0.94,
                  "legend": {"0": "calm", "1": "frustrated", "2": "very angry"},
                  "probabilities": {"0": 0.0, "1": 0.96, "2": 0.04}}
}
```

| field | on which type | what it is |
|---|---|---|
| `noul` | noul | The probability that the answer is yes. Compare it to a threshold you choose; the package default in `strands_jev/questions.py` is {{n:noul_threshold}}. |
| `choice` | choice | The option with the highest probability, by the key you gave in `criteria`. |
| `confidence` | choice, score | How sure the model is of the winning option or level, 0 to 1. A three-way choice split 0.4/0.3/0.3 has a winner and a low confidence at once. |
| `probabilities` | choice, score | Every option or level with its probability. Read this when the second place matters, or when you want your own threshold. |
| `score` | score | The probability-weighted position on the scale, index 0 the first level: 1.04 sits just above "frustrated". Do not average scores across items; read the legend. |
| `legend` | score | Index to level name, so a score is never a bare number in a log. |
| `model` | the result | The versioned id that answered, `jev-1.13.0` on {{n:live_date}}, even when the request said `jev-latest`. |
| `latency_ms`, `input_tokens` | the result | This request's wall clock and billed tokens. |

## What just happened

Three questions, one forward pass. Questions cannot see each other's answers, so a follow-up question is asked alongside the question that decides whether it matters; the [fan-out pattern](../learn/patterns.md) builds on that. Keys such as `urgent` are yours; the model never sees them. Everything the model does see is `state`, `instructions` and `criteria`, so that is where the care goes: [State](../learn/state.md).

## Refusals

The tools refuse before they spend. A `criteria` list of one level for a score, a `type` that is not one of the three, a `questions` value that is not a mapping, list or JSON string: each returns `status: "error"` with the fix in the text and no request sent. An oversized request is refused the same way by the budget check, described on [What it costs](cost.md).
