---
description: The sibling package. Interventions behind the agent there; tools in front of it here.
---

# strands-decisions

[mikegc-aws/strands-decisions](https://github.com/mikegc-aws/strands-decisions) puts a decision model **behind** a Strands agent: intervention handlers that run on the agent's own events (before a tool call, on a message, on a loop) and let a decision model approve, classify or stop what the agent was about to do. The agent does not know it is being judged.

This package puts Jev **in front** of the agent: tools the agent chooses to call when it wants a judgement it can act on. The agent knows, because it asked.

| | strands-decisions | strands-jev |
|---|---|---|
| where the model sits | in the agent loop, as an `InterventionHandler` | in the tool list, as `@tool` functions |
| who decides to ask | the framework, on every matching event | the chat model, or your code via `agent.tool.<name>` |
| what it is for | policy, guardrails, loop control over the agent's actions | judgements about the agent's data and inputs |
| decision model | pluggable; Jev is one option | Jev only |

They compose. An agent can carry these tools and run under those handlers at the same time; the handler judges the agent, the tools let the agent judge the world. Nothing here duplicates an intervention handler, by design.
