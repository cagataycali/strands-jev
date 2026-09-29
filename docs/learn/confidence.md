---
description: Probabilities, the confidence derived from them, and thresholds that scale with the stakes.
---

# Confidence

Follows [docs.typesafe.ai/confidence](https://docs.typesafe.ai/confidence).

Every Choice and Score answer carries `probabilities`, the distribution over your options or levels. Its shape is the certainty: concentrated on one outcome is a confident answer, spread out is not. `confidence` collapses that shape into one number from 0 to 1 so code can threshold without doing the arithmetic. Noul answers carry no `confidence`; the `noul` probability is the whole answer, and its distance from 0.5 is your certainty.

## Read the winner, not the average

A three-way Choice split 0.40 / 0.30 / 0.30 has a winner and a low confidence at once. Act on `choice` only when `confidence` clears the floor; below it, the honest reading is "no clear winner". For a Score the same applies to the levels: a flat distribution across "calm / frustrated / very angry" means the scale did not fit, not that the writer is medium.

The `probabilities` field is there so you are not locked into TypeSafe's definition of confidence. Margin between first and second, entropy, mass above a level: compute what your decision needs.

## Three bands

The docs suggest three ranges with three behaviours. High: act. Medium: proceed with a check, a confirmation or a flag. Low: do not act; route to a person or another system. Where the bands sit depends on the stakes, and the same system should gate different actions at different levels: showing the wrong balance screen is recoverable, approving the wrong transfer is not.

```python
r = agent.tool.route(
    message=text,
    intents={"check_balance": "view the balance", "approve_transfer": "approve the pending withdrawal", "support": "get help"},
    min_confidence={{n:confidence_floor}},
    thresholds={"approve_transfer": 0.9},
)
```

`route` implements exactly that: one floor for every intent, a higher one for the risky ones, and `escalate: true` with a `reason` whenever a floor is not met.

## Where the numbers live

The package's defaults are constants in `strands_jev/questions.py`: confidence floor {{n:confidence_floor}} (the confidence-routing pattern's value), Noul threshold {{n:noul_threshold}}, an uncertain band of {{n:uncertain_margin}} either side of it. The docs are explicit that these are starting points: set production thresholds from your own labelled data, conservatively at first, and read [Measured](../measured/index.md) for how a floor behaved on real cases (a 3-level Score's confidence sat at 0.42 and 0.43 on two clear lookups, which is why `route` gates complexity only on the intents you name).
