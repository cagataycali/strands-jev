"""mkdocs hook: numbers the docs never type by hand.

Every ``{{n:key}}`` token in a page is replaced at build time with a value read from the
tree, so a count cannot drift from the code or the measurement it describes. An unknown key
fails the build (``mkdocs build --strict`` turns the hook's ``log.warning`` into an error),
so a typo cannot ship as a literal ``{{n:...}}``.

Sources, in the order the keys below list them:

* ``src/strands_jev/questions.py``: every module constant, as ``{{n:q.NAME}}``
  (``{{n:q.PRICE_PER_MILLION_INPUT_TOKENS}}`` prints ``0.042``); the ones read most often
  have short names: ``price_per_mtok``, ``max_request_tokens``, ``max_state_tokens``,
  ``max_choice_options``, ``max_score_levels``, ``max_questions``, ``max_items``,
  ``max_concurrency``, ``confidence_floor``, ``noul_threshold``.
* ``src/strands_jev/tools``: ``tools`` (``@tool`` decorators), ``tools_primitives``,
  ``tools_patterns``, ``tools_cookbooks`` (the ``*_TOOLS`` lists), ``groups``.
* ``tests``: ``unit_tests`` (``def test_`` in ``tests/*.py``), ``live_tests`` (the same in
  ``tests/live``).
* ``tests/live/results.json`` when it exists, else the table in ``tests/live/RESULTS.md``:
  ``live_tools`` (tools with a measured row), ``live_cases``, ``live_jev_correct``,
  ``live_baseline_correct``, ``live_calls``, ``live_tokens``, ``live_cost`` (USD, six
  decimals), ``live_cost_cents`` (one decimal), ``live_mean_ms`` (call-weighted),
  ``live_model`` (the versioned id), ``live_date``.
* ``pyproject.toml``: ``python_min``, ``version``.

Filesystem only, no ``strands_jev`` import, so a failing import cannot hide a number.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger("mkdocs.hooks.facts")

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src" / "strands_jev"
_TESTS = _REPO / "tests"
_TOKEN = re.compile(r"\{\{\s*n:([A-Za-z_.]+)\s*\}\}")

_SHORT = {
    "price_per_mtok": "PRICE_PER_MILLION_INPUT_TOKENS",
    "max_request_tokens": "MAX_REQUEST_TOKENS",
    "max_state_tokens": "MAX_STATE_PLUS_QUESTION_TOKENS",
    "max_choice_options": "MAX_CHOICE_OPTIONS",
    "max_score_levels": "MAX_SCORE_LEVELS",
    "min_score_levels": "MIN_SCORE_LEVELS",
    "max_questions": "MAX_QUESTIONS_PER_REQUEST",
    "max_items": "MAX_ITEMS_PER_BATCH",
    "max_concurrency": "MAX_CONCURRENCY",
    "max_state_chars": "DEFAULT_MAX_STATE_CHARS",
    "chars_per_token": "CHARS_PER_TOKEN",
    "confidence_floor": "DEFAULT_CONFIDENCE_FLOOR",
    "noul_threshold": "DEFAULT_NOUL_THRESHOLD",
    "uncertain_margin": "DEFAULT_UNCERTAIN_MARGIN",
}

_GROUPS = (("primitives", "PRIMITIVE_TOOLS"), ("patterns", "PATTERN_TOOLS"), ("cookbooks", "COOKBOOK_TOOLS"))


def _constants(path: Path) -> dict[str, Any]:
    """Module-level ``NAME = <literal>`` assignments in a file, evaluated as literals."""
    out: dict[str, Any] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return out


def _list_length(path: Path, name: str) -> int | None:
    """Length of a module-level list literal ``name = [a, b, ...]``, or None when absent."""
    if not path.exists():
        return None
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            if isinstance(node.value, ast.List | ast.Tuple):
                return len(node.value.elts)
    return None


def _count_tests(paths: list[Path]) -> int:
    return sum(len(re.findall(r"^\s*(?:async )?def test_", p.read_text(encoding="utf-8"), re.M)) for p in paths)


def _results_rows() -> list[dict[str, Any]]:
    """The live rows: ``results.json`` when present, else the first table in RESULTS.md."""
    js = _TESTS / "live" / "results.json"
    if js.exists():
        rows = json.loads(js.read_text(encoding="utf-8"))
        return list(rows if isinstance(rows, list) else rows.get("rows", []))
    md = _TESTS / "live" / "RESULTS.md"
    if not md.exists():
        return []
    text = md.read_text(encoding="utf-8")
    head = re.search(r"^## (\d{4}-\d{2}-\d{2}), (jev-[\w.]+)", text, re.M)
    date, model = (head.group(1), head.group(2)) if head else ("", "")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 8 or cells[0] in {"tool", "---"} or not re.match(r"^\d+/\d+$", cells[2]):
            continue
        tool, cases, jev, base, calls, tokens, cost, ms = cells
        jev_c, jev_n = (int(x) for x in jev.split("/"))
        base_c, _ = (int(x) for x in base.split("/"))
        rows.append(
            {
                "tool": tool.strip("`"),
                "cases": jev_n,
                "cases_text": cases,
                "jev_correct": jev_c,
                "baseline_correct": base_c,
                "calls": int(calls.replace(",", "")),
                "input_tokens": int(tokens.replace(",", "")),
                "cost_usd": float(cost),
                "mean_ms": float(ms.replace(",", "")),
                "model": model,
                "date": date,
            }
        )
    return rows


@lru_cache(maxsize=1)
def numbers() -> dict[str, Any]:
    """Derive every number once per build."""
    out: dict[str, Any] = {}
    consts = _constants(_SRC / "questions.py")
    for name, value in consts.items():
        if isinstance(value, int | float | str) and not isinstance(value, bool):
            out[f"q.{name}"] = value
    for short, name in _SHORT.items():
        if name in consts:
            out[short] = consts[name]

    tools = 0
    for path in (_SRC / "tools").glob("*.py"):
        tools += len(re.findall(r"^\s*@tool\b", path.read_text(encoding="utf-8"), re.M))
    out["tools"] = tools
    groups = 0
    for group, list_name in _GROUPS:
        n = _list_length(_SRC / "tools" / f"{group}.py", list_name)
        out[f"tools_{group}"] = n or 0
        groups += 1 if n else 0
    out["groups"] = groups

    out["unit_tests"] = _count_tests(sorted(_TESTS.glob("test_*.py")))
    out["live_tests"] = _count_tests(sorted((_TESTS / "live").glob("test_*.py")))

    rows = _results_rows()
    calls = sum(r["calls"] for r in rows)
    out["live_tools"] = len(rows)
    out["live_cases"] = sum(r["cases"] for r in rows)
    out["live_jev_correct"] = sum(r["jev_correct"] for r in rows)
    out["live_baseline_correct"] = sum(r["baseline_correct"] for r in rows)
    out["live_calls"] = calls
    out["live_tokens"] = sum(r["input_tokens"] for r in rows)
    cost = sum(r["cost_usd"] for r in rows)
    out["live_cost"] = f"{cost:.6f}"
    out["live_cost_cents"] = f"{cost * 100:.1f}"
    out["live_mean_ms"] = round(sum(r["mean_ms"] * r["calls"] for r in rows) / calls) if calls else 0
    out["live_model"] = rows[0]["model"] if rows else "unmeasured"
    out["live_date"] = rows[0]["date"] if rows else "unmeasured"

    pyproject = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'requires-python\s*=\s*">=([\d.]+)"', pyproject)
    out["python_min"] = m.group(1) if m else "3.10"
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    out["version"] = m.group(1) if m else "0"
    return out


def render(value: Any) -> str:
    """Integers with thousands separators; everything else as written."""
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def substitute(markdown: str, page_path: str = "<string>") -> str:
    """Replace every ``{{n:key}}`` in ``markdown``; warn on an unknown key."""
    values = numbers()

    def _one(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            log.warning("%s: unknown numbers key {{n:%s}}", page_path, key)
            return match.group(0)
        return render(values[key])

    return _TOKEN.sub(_one, markdown)


def on_page_markdown(markdown: str, page, config, files) -> str:  # noqa: ANN001 - mkdocs signature
    """mkdocs hook entry point: expand every ``{{n:key}}`` token."""
    return substitute(markdown, page.file.src_path)


if __name__ == "__main__":
    for key, value in sorted(numbers().items()):
        print(f"{key:40} {render(value)}")
