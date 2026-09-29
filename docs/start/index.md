---
description: Four pages, in order, from an empty environment to an agent that asks Jev before it acts.
cta: true
copy_prompt: true
---

# Start

You leave with the package installed and your key in place, one decision made from Python with every answer field explained, an agent that routes a request through Jev, directly and then on the model's own initiative, and the line on the bill that all of it cost.

| page | you leave with |
|---|---|
| [Install](install.md) | `strands-jev` in a Python `{{n:python_min}}` or later environment, the key in `TYPESAFE_API_KEY` or `~/.typesafe`, `jev_models` answering |
| [First decision](first-decision.md) | one `jev_ask` call, three typed answers, what `noul`, `choice`, `confidence`, `score` and `legend` mean |
| [First agent](first-agent.md) | `Agent(tools=ALL_TOOLS)`, a direct `route` call, a chat turn where the model picks the tool |
| [What it costs](cost.md) | the price line, the budget check that refuses an oversized request, the measured cost of the live suite |

Every `python` fence on these pages runs against this commit. The ones that talk to `api.typesafe.ai` spend money at ${{n:price_per_mtok}} per million input tokens; the amounts are in the text next to them.
