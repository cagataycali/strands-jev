---
description: What Jev reads. Strings, objects and arrays, paths into them, and structured questions.
---

# State

Follows [docs.typesafe.ai/concepts/state](https://docs.typesafe.ai/concepts/state) and the advanced-structure section of [primitives](https://docs.typesafe.ai/primitives).

State is the material you put in front of the model before asking. The docs' image: what you would hand a panel of experts before asking for their judgement. One request evaluates one state against every question in it.

## Three shapes

| shape | use it for | example |
|---|---|---|
| string | one message, passage or article | `"My card was charged twice."` |
| object | named fields, related records, application state | `{"message": "...", "order_id": "A-104"}` |
| array | a sequence of messages or records | `["Hi", "My customer number is TS1337.", "My card was charged twice."]` |

Use an object for most requests. Field names carry meaning to the model, and a question can point into the object with a backticked path:

```python
state = {
    "ticket": {"subject": "Duplicate charge",
               "messages": [{"from": "customer", "text": "I was charged twice for A-104."},
                            {"from": "support", "text": "We are checking the charges."}]},
    "order": {"id": "A-104", "charges": [{"amount_usd": 49}, {"amount_usd": 49}]},
    "refund_policy": "Duplicate charges are eligible for a refund.",
}
questions = {
    "asks_refund": "Does `ticket.messages[0].text` ask for a refund?",
    "policy_covers": "Does `refund_policy` cover what `ticket.messages[0].text` describes?",
}
```

Text only at jev-1.13: strings, objects and arrays of text. No images, audio or video.

## Keep content and questions apart

The state holds the facts: the message, the order, the policy. The questions hold the judgements: did they ask, does the policy allow. Do not fold the policy into the instructions of a question; put it in the state where every question can read it, and ask about it by path.

## Structured instructions and criteria

Instructions and criteria may be JSON values rather than strings when the question has structure of its own: a rubric with named parts, a set of examples, a list of fields to compare. The SDK serialises them; the model reads them as part of the question. `jev_ask` passes them through unchanged.

## How much state

Two limits from the API: {{n:max_state_tokens}} tokens for the state plus the longest question, {{n:max_request_tokens}} per request. The client estimates and refuses before sending ([What it costs](../start/cost.md)). Well under those limits, less is still better: the jaggedness page reports that large irrelevant state moves answers, so the many-item tools in this package send one item per request rather than a list, and `render_state` truncates a single item at {{n:max_state_chars}} characters with a marker. Filter first, then ask.
