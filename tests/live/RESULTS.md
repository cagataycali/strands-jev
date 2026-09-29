# Live results

Every number here was measured by running `hatch run live` against `api.typesafe.ai` with
the model alias `jev-latest`. The versioned id that answered is in the table. Cost is
input tokens times $0.042 per million (docs.typesafe.ai/models, read 2026-09-29); the API
reports tokens, not dollars. Latency is the client-side wall clock per request from a
laptop, so it includes the network.

Baselines are the deterministic code a developer would write without a model. A live test
fails when Jev loses to its baseline, and also when the baseline gets full marks, because a
case set the baseline aces measures nothing.

## 2026-09-29, jev-1.13.0

| tool | cases | Jev | baseline | calls | input tokens | cost USD | mean ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| jev_ask | 8 messages x 3 questions | 7/8 | 5/8 | 8 | 3,519 | 0.000148 | 179 |

jev_ask: each message carries a noul (urgency), a choice (billing, technical, sales) and a
3-level score (frustration); a case counts only when all three match the label. The
baseline is keyword rules (exclamation marks and time words for urgency, vocabulary for the
team, anger words for frustration). Jev's one miss: "This is unacceptable. Charged twice, no
reply for a week, and now you want a screenshot?" labelled not urgent, Jev said urgent
(noul over 0.5). The baseline missed the same case and two more (a "since Tuesday" outage
with no exclamation mark read as not urgent; a "go live tomorrow" message scored calm).

Total spend this table: $0.000148 over 8 calls.
