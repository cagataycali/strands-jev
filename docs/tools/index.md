---
description: Every tool in the package, generated from the specs the agent reads.
---

# Tools

{{n:tools}} tools in {{n:groups}} groups. This page and the three behind it are generated at build time from `strands_jev.tools`: the name, the description and the parameter table are the `tool_spec` a Strands `Agent` hands its model, so what you read here is what the model reads. The last column is the live score from [Measured](../measured/index.md), where a tool has one.

{{tools_index}}

Every tool returns `{"status": "success" | "error", "content": [{"json": ...}, {"text": ...}]}`: the JSON first, then a one-line summary. An error names the fix and sends nothing. Endpoint resolution is the same everywhere: `invocation_state["jev"]`, then `strands_jev.configure(...)`, then a `Jev()` from the key on the machine.

- [Primitives](primitives.md): the raw API, the model list, the usage tally.
- [Patterns](patterns.md): the four patterns from the TypeSafe docs, questions already written.
- [Cookbooks](cookbooks.md): the cookbooks, in the order their measured value put them.
