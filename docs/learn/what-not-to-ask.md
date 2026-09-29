---
description: The jaggedness list for jev-1.13, as guidance. What Jev reads wrong, and what to do in code instead.
---

# What not to ask

Follows [docs.typesafe.ai/model-jaggedness/jev-1.13](https://docs.typesafe.ai/model-jaggedness/jev-1.13). "Jagged" is the docs' word: strong on judgement, weak on a short list of things a person would find easy. The list is the model's, for this version; the fixes are the package's.

| do not ask Jev to | because | do instead |
|---|---|---|
| count or do arithmetic | it reads literally and does not compute | count in code: one Noul per item, then `sum` |
| compare dates or times | "before" and "after" are computed, not read | extract the parts as Choice questions with a "not stated" option, assemble and compare in code |
| follow indirection | "the thing the second speaker referred to" loses the model | resolve the reference in the state, or point at it with a backticked path |
| read a large state for a small answer | irrelevant material moves the answer | filter to what the questions need; one item per request for lists |
| judge adversarial content as if it were neutral | text that argues for an answer moves the answer | keep untrusted text in a named field, ask about it, do not let it write the instructions |
| generate anything | there is no text output | let the chat model write; let Jev judge what it wrote |
| re-type a value | a value copied by the model can drift | offer pre-parsed candidates and ask which one; copy verbatim in code |

Two more rules of thumb from the same page: align the criteria with the instructions, so the model is not asked one thing and given answer descriptions for another; and treat every threshold as a starting point to be set from your own data.

## What this looks like in a tool

```python
r = agent.tool.jev_ask(
    state={"lines": ["Refund issued 2026-09-12", "Card charged 2026-09-14", "Card charged 2026-09-14"]},
    questions={f"dup_{i}": f"Is `lines[{i}]` a charge that also appears elsewhere in `lines`?" for i in range(3)},
)
duplicates = sum(1 for a in r["content"][0]["json"]["answers"].values() if a["noul"] >= {{n:noul_threshold}})
```

Three Nouls, one request, the count in Python. The model judged; the code counted.
