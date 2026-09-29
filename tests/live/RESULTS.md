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

The two sections below were run in two sessions of the same suite on the same day.

| tool | cases | Jev | baseline | calls | input tokens | cost USD | mean ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| jev_ask | 8 messages x 3 questions | 7/8 | 5/8 | 8 | 3,519 | 0.000148 | 179 |
| fan_out | 12 tickets, 4 questions each | 10/12 | 8/12 | 12 | 5,506 | 0.000231 | 159 |
| route | 14 messages, intent + handler | 14/14 | 11/14 | 14 | 6,886 | 0.000289 | 179 |
| composite_score | 30 ordered pairs, 6 resumes x 2 profiles | 27/30 | 20/30 | 6 | 3,313 | 0.000139 | 213 |
| function_call | 16 commands, function + every argument | 14/16 | 10/16 | 16 | 29,830 | 0.001253 | 172 |
| rerank | 6 queries x 8 passages, top-1 | 6/6 | 0/6 | 48 | 17,746 | 0.000745 | 178 |
| find_lines | 8 queries over a 21-line contract | 7/8 | 2/8 | 8 | 6,750 | 0.000284 | 158 |
| extract_value | 8 documents, verbatim pick | 8/8 | 2/8 | 8 | 3,130 | 0.000131 | 162 |
| extract_date | 8 documents, 7 Choices each | 8/8 | 5/8 | 8 | 13,381 | 0.000562 | 144 |
| verify_citations | 10 citations over 2 sources | 8/10 | 5/10 | 9 | 4,343 | 0.000182 | 216 |
| count_matching | 12 log lines | 11/12 | 9/12 | 12 | 3,814 | 0.000160 | 184 |

jev_ask: each message carries a noul (urgency), a choice (billing, technical, sales) and a
3-level score (frustration); a case counts only when all three match the label. The
baseline is keyword rules (exclamation marks and time words for urgency, vocabulary for the
team, anger words for frustration). Jev's one miss: "This is unacceptable. Charged twice, no
reply for a week, and now you want a screenshot?" labelled not urgent, Jev said urgent
(noul over 0.5). The baseline missed the same case and two more (a "since Tuesday" outage
with no exclamation mark read as not urgent; a "go live tomorrow" message scored calm).

fan_out: support-ticket triage, one request with a category Choice, a severity Score, a
repro Noul and a refund Noul; severity and repro apply only to bug reports, refund only to
billing, and the tool reports the rest under skipped. A case counts when the category and
every applicable follow-up match. Both misses are severity one level high: an image lost on
every paste, and a phone app that crashes on rotation, labelled degraded, scored down. The
keyword baseline mislabelled a bug phrased as a wish ("what I would really love is for the
app to stop crashing") as a feature request, and read "take back the last payment" as no
refund.

route: 4 intents plus none_of_these and a 3-level complexity Score in one request,
confidence floor 0.6, complexity gate applied to complaints only, as the pattern does. First
run with the gate on every intent sent two clear lookups to a person because the 3-level
score spread its probability (confidence 0.42 and 0.43 under the pattern's 0.5 floor); that
is why the tool takes complex_intents. Every complaint case escalated for the right reason.

composite_score: 3 dimensions (Python depth, leadership, system design) on 6 short
resumes, one request each, two weight profiles. A pair counts when the resume a reader
ranked higher gets the higher composite. Jev's 3 misses are close calls (a staff engineer
who led a four-team migration edges the engineering manager on the manager profile, 0.717
to 0.677; a robotics-club captain with two internships edges a data analyst). The keyword
baseline was fooled by a resume built of the right words and none of the substance.

function_call: 7 functions, 30 questions per command (a Choice over functions plus
none_of_these; per argument a Choice, a set of Nouls, a flag Noul, and a stated Noul). A
case counts when the function and every argument match exactly. Misses: "show me apple
daily with volume" came back none_of_these at 0.45 (an earlier run of the same command
returned plot_price with all three arguments, so this one sits on the boundary); "is amd
tracking nvidia lately" filled window=3mo where the cookbook leaves it unset ("lately" read
as stated, 0.5 or over). The keyword baseline had no rule for "swinging", "fell hardest",
"the s&p by the hour", "what have you got data on" or "side by side".

rerank: each of 8 short policy passages has a lexical decoy (a passage that shares its
words but answers nothing). Six paraphrased queries, one Noul per query and passage pair, 48
requests. Jev put the right passage first every time; token Jaccard overlap never did, which
is what the decoys were for.

find_lines: a 21-line contract sent once per query as numbered lines, a Choice over 21 line
ids plus a presence Noul. Two of the eight queries have no answer in the text. Jev's one
miss: "In which country's courts would a dispute be heard?" reported not found at presence
0.29 (the line says "governed by the laws of Ireland"; the question reads through
"courts", which the jaggedness page calls indirection). The unanswerable "Can I resell the
service" came back at presence 0.04. The word-overlap baseline needs two shared words to
claim a hit and found almost nothing in paraphrased questions.

extract_value: regex finders produce the candidate spans (emails, amounts, dates, phones);
one Choice over them plus none_of_these. Every pick was the right span, verbatim. The
baseline (first span, or last after "instead"/"rather than"/"moved") got 2.

extract_date: seven Choices per document, assembled in code from today = 2026-09-29 (a
Tuesday). All eight right, including "next Thursday" (2026-10-08), a bare "Thursday"
(2026-10-01), "Jan 5" rolling to 2027, and two documents that state no date. The regex
baseline missed the bare weekday arithmetic, the year rollover and one no-date case.

verify_citations: two present quotes were misread. "Equipment is provided for the home
office" against the claim "the policy covers laptops and monitors" came back says_nothing
at 0.58 (a reader would call that supported); "Section 4. Equipment is provided" against
"remote workers get a stipend" came back contradicts at 0.30 (labelled unsupported). Both
are under the cookbook's 0.7 floor, so the tool reported them for review rather than as
decisions. Every contradiction and the missing quote were caught. The baseline calls any
present quote verified.

count_matching: one Noul per log line, counted in code. The miss: "connection to db-2
re-established after 4 s" (labelled as something having gone wrong) read as routine at
INFO level. The grep baseline flagged a DEBUG line about error budget and a release note
containing the word failure.

Total spend this table: $0.004125 over 149 calls, 98,218 input tokens.
