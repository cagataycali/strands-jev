---
description: The package, the key, and one call that proves the two have met.
---

# Install

At the end of this page `from strands_jev import ALL_TOOLS` works and `jev_models` returns the model ids the endpoint serves.

## Requirements

Python `{{n:python_min}}` or later. No GPU, no local model: Jev is a hosted endpoint, and this package is a thin layer over the official `typesafe-sdk` and `strands-agents`.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install git+https://github.com/cagataycali/strands-jev
```

The package is not on PyPI yet. When it is, the line becomes `pip install strands-jev`; until then the git URL above installs the same wheel.

## The key

Get a TypeSafe API key from [typesafe.ai](https://typesafe.ai). The client looks in two places, in this order:

1. the environment variable `TYPESAFE_API_KEY`;
2. the file `~/.typesafe`, one line, the key.

```bash
echo "<your key>" > ~/.typesafe && chmod 600 ~/.typesafe
```

The package never writes the key anywhere, never logs it, and `.gitignore` in the repo lists `.env`, `*.key` and `.typesafe`. A missing key is a `RuntimeError` naming both places at the first call, not at import.

## Check

```python
import asyncio
from strands_jev import Jev

async def main():
    jev = Jev()
    for row in await jev.models():
        print(row["name"], row.get("description", ""))

asyncio.run(main())
```

You should see `jev-latest` and `jev-preview`, both aliases that resolved to `jev-1.13.0` on {{n:live_date}}. Pin a versioned id with `Jev(model="jev-1.13.0")` when thresholds were tuned against it; `jev-latest` follows releases.

This call is free: `GET /v1/models` carries no tokens. The next page sends the first request that is billed.
