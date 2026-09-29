---
description: Noul, Choice and Score. When to use which, and what comes back.
---

# Primitives

Follows [docs.typesafe.ai/primitives](https://docs.typesafe.ai/primitives). Every tool in this package is built from these three; `jev_ask` exposes them directly.

| primitive | the question shape | comes back as | reach for it when |
|---|---|---|---|
| **Noul** | yes or no | `noul`, the probability of yes | one fact about the state: does it ask for a refund, is it urgent, does the claim appear in the source |
| **Choice** | pick one of the options you list, up to {{n:max_choice_options}} | `choice`, `confidence`, `probabilities` over every option | classification, routing, picking a candidate, extracting a value from a closed set |
| **Score** | place the state on an ordered scale of {{n:min_score_levels}} to {{n:max_score_levels}} levels you describe | `score` (probability-weighted position, index 0 the first level), `confidence`, `legend`, `probabilities` | severity, frustration, quality, fit: anything with an order |

## Writing them

Each question has `instructions`, the question the model reads, and optional `criteria`, which say what each answer means. For a Noul the criteria are `true` and `false` descriptions; for a Choice they map each option to when it applies; for a Score they are the ordered level descriptions. In `jev_ask` a question is a plain dict:

```python
questions = {
    "urgent": {"type": "noul", "instructions": "Does this convey urgency?",
               "criteria": {"true": "the writer needs action now", "false": "it can wait"}},
    "team": {"type": "choice", "instructions": "Which team should take this?",
             "criteria": {"billing": "charges and payouts", "technical": "bugs and outages"}},
    "severity": {"type": "score", "instructions": "How bad is the impact?",
                 "criteria": ["cosmetic", "degraded", "blocked"]},
}
```

A bare string is a Noul. A list of specs is named `q1..qN`. Instructions and criteria may be JSON objects instead of strings when the question itself has structure; see [State](state.md).

## Reading them

A Noul is a probability, not a verdict: compare it to a threshold your code owns. A Choice's `choice` is the top option; look at `probabilities` when the runner-up matters, and add a `none_of_these` option when nothing may fit (the routing tools do this for you). A Score's `score` is a position on your scale, and `legend` names the levels, so read "1.04, just above frustrated" rather than "1.04". Noul answers carry no `confidence`; the probability is the whole answer.

## The constraints

Options in a Choice: {{n:max_choice_options}}. Levels in a Score: {{n:min_score_levels}} to {{n:max_score_levels}}, in order, index 0 first. Question keys are yours and are not shown to the model. All of these are checked by the tools before a request is sent; a violation is an error naming the limit, not a clamped request.
