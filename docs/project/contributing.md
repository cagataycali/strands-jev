---
description: Two virtual environments, one command before every push, and the docs build.
---

# Contributing

## Package

```bash
git clone https://github.com/cagataycali/strands-jev && cd strands-jev
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
hatch run prepare
```

`prepare` runs `ruff format`, `ruff check`, `mypy src` and the unit tests, {{n:unit_tests}} of them at this commit, all against a scripted fake endpoint, no network. It is what CI runs on every push and pull request for Python {{n:python_min}} through 3.13.

## Live suite

```bash
hatch run live
```

Needs the key on the machine and spends money: the whole suite cost ${{n:live_cost}} on {{n:live_date}}. Every live test scores a tool against its code baseline and fails when the model loses or when the baseline gets full marks; see [Method](../measured/method.md). New numbers go into `tests/live/RESULTS.md`, which this site renders unchanged.

## House style

Google docstrings with `Args` and `Returns` on every tool: the reference pages are generated from them. Questions and thresholds live in `strands_jev/questions.py`, nowhere else. Tolerate inputs whose intent is unambiguous, refuse the rest before spending, never clamp silently, and name the fix in every error. No em or en dashes in prose; every number sourced to a measurement or a docs page.

## Docs

```bash
python3 -m venv .venv-docs && .venv-docs/bin/pip install -e . -r docs/requirements.txt
.venv-docs/bin/mkdocs build --strict
.venv-docs/bin/mkdocs serve -a 127.0.0.1:8092
```

The build is strict: an unknown `n:` token, a dash in prose, a site over the word ceiling or a broken link fails it. The Tools pages come from the `@tool` specs, the numbers from `docs/hooks/facts.py`; edit the source, not the page. Pushes to `main` that touch `docs/`, `mkdocs.yml`, `overrides/` or `src/` rebuild the site.
