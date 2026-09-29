"""mkdocs hook: the Tools reference, generated from the ``@tool`` specs.

Two tokens, each on a line of its own:

* ``{{tools_index}}``: one table over every tool: name, group, first docstring line, the
  live score when ``tests/live`` measured it.
* ``{{tools_ref:<group>}}``: one section per tool in that group (``primitives``,
  ``patterns``, ``cookbooks``): the description the agent reads, a parameters table taken
  from the tool's JSON input schema (name, type, default, description), the result shape
  from the docstring's ``Returns:`` section, the docs.typesafe.ai page it ports, and the
  live row for that tool.

The source of truth is ``strands_jev.tools``: the module is imported and every tool's
``tool_spec`` is read, so what the site shows is what the model is handed. Group membership
comes from the ``PRIMITIVE_TOOLS`` / ``PATTERN_TOOLS`` / ``COOKBOOK_TOOLS`` lists; the ported
page from a ``PORTS`` mapping when the package exposes one, else from the first
``docs.typesafe.ai/...`` reference in the docstring. ``python docs/hooks/tools_ref.py``
prints the markdown for a look.
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger("mkdocs.hooks.tools_ref")

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
_INDEX = re.compile(r"^\{\{\s*tools_index\s*\}\}\s*$", re.M)
_GROUP = re.compile(r"^\{\{\s*tools_ref:([a-z_]+)\s*\}\}\s*$", re.M)
_DOCS_REF = re.compile(r"docs\.typesafe\.ai/([A-Za-z0-9_./#-]+?)(?=[\s)\],;:]|$)")
_GROUPS = {"primitives": "PRIMITIVE_TOOLS", "patterns": "PATTERN_TOOLS", "cookbooks": "COOKBOOK_TOOLS"}
_TYPES = {"string": "str", "object": "dict", "array": "list", "integer": "int", "number": "float", "boolean": "bool", "null": "None"}


def _facts():  # noqa: ANN202 - sibling hook loaded by path so mkdocs and the CLI agree
    spec = importlib.util.spec_from_file_location("jev_docs_facts", _HERE / "facts.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _md(text: str) -> str:
    """rst-ish docstring prose to markdown: ``x`` to `x`, stray triple backticks folded."""
    text = text.replace("```", "`")
    text = re.sub(r"``([^`]+)``", r"`\1`", text)
    return text.strip()


def _cell(text: str) -> str:
    return _md(text).replace("\n", " ").replace("|", "\\|")


def _type(schema: dict[str, Any]) -> str:
    if "anyOf" in schema:
        return " \\| ".join(dict.fromkeys(_type(s) for s in schema["anyOf"]))
    if "enum" in schema:
        return " \\| ".join(f"`{v!r}`" for v in schema["enum"])
    kind = schema.get("type")
    if isinstance(kind, list):
        return " \\| ".join(_TYPES.get(k, k) for k in kind)
    if kind == "array" and isinstance(schema.get("items"), dict) and schema["items"].get("type"):
        return f"list[{_type(schema['items'])}]"
    return _TYPES.get(kind, kind or "any")


def _default(schema: dict[str, Any], required: bool) -> str:
    if required:
        return "required"
    if "default" not in schema:
        return ""
    value = schema["default"]
    return "`None`" if value is None else f"`{value!r}`"


def _returns(func: Any) -> str:
    doc = inspect.getdoc(func) or ""
    m = re.search(r"^Returns:\n((?:[ \t]+.*\n?)+)", doc, re.M)
    if not m:
        return ""
    return _md(" ".join(line.strip() for line in m.group(1).splitlines()))


def _summary(description: str) -> str:
    return _md(description.strip().split("\n", 1)[0])


def _body(description: str) -> str:
    """The description after its first line, without the Returns section the spec keeps."""
    parts = description.strip().split("\n", 1)
    if len(parts) < 2:
        return ""
    body = re.sub(r"^Returns:\n(?:[ \t]+.*\n?)+", "", parts[1], flags=re.M)
    body = _DOCS_REF.sub(lambda m: f"[docs.typesafe.ai/{m.group(1)}](https://docs.typesafe.ai/{m.group(1).split('#')[0]})", body)
    return _md(body)


@lru_cache(maxsize=1)
def catalogue() -> dict[str, list[dict[str, Any]]]:
    """Every tool, by group, with its spec fields unpacked."""
    src = str(_REPO / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    import strands_jev.tools as tools  # noqa: PLC0415 - imported here so the hook loads without the package

    ports: dict[str, str] = dict(getattr(tools, "PORTS", {}) or {})
    rows = {r["tool"]: r for r in _facts()._results_rows()}
    out: dict[str, list[dict[str, Any]]] = {}
    for group, attr in _GROUPS.items():
        entries: list[dict[str, Any]] = []
        for tool in getattr(tools, attr, []) or []:
            spec = tool.tool_spec
            schema = spec["inputSchema"]["json"]
            required = set(schema.get("required", []))
            description = spec.get("description", "")
            ported = ports.get(spec["name"])
            if not ported:
                found = _DOCS_REF.findall(description)
                ported = ", ".join(dict.fromkeys(found)) if found else ""
            entries.append(
                {
                    "name": spec["name"],
                    "summary": _summary(description),
                    "body": _body(description),
                    "params": [
                        (name, _type(s), _default(s, name in required), _cell(s.get("description", "")))
                        for name, s in schema.get("properties", {}).items()
                    ],
                    "returns": _returns(getattr(tool, "_tool_func", None)),
                    "ports": ported,
                    "live": rows.get(spec["name"]),
                }
            )
        out[group] = entries
    return out


def _live_cell(row: dict[str, Any] | None) -> str:
    if not row:
        return "not yet"
    return f"{row['jev_correct']}/{row['cases']} vs {row['baseline_correct']}/{row['cases']}, {round(row['mean_ms'])} ms"


def index_markdown() -> str:
    lines = ["| tool | group | what it does | Jev vs baseline, mean latency |", "| --- | --- | --- | --- |"]
    for group, entries in catalogue().items():
        for e in entries:
            lines.append(f"| [`{e['name']}`]({group}.md#{e['name']}) | {group} | {e['summary']} | {_live_cell(e['live'])} |")
    return "\n".join(lines)


def group_markdown(group: str) -> str:
    entries = catalogue().get(group, [])
    if not entries:
        return "No tools in this group yet. The reference appears here when the first one lands in the source."
    out: list[str] = []
    for e in entries:
        out.append(f"## `{e['name']}`\n")
        out.append(e["summary"] + "\n")
        if e["body"]:
            out.append(e["body"] + "\n")
        if e["params"]:
            out.append("| parameter | type | default | description |")
            out.append("| --- | --- | --- | --- |")
            for name, kind, default, desc in e["params"]:
                out.append(f"| `{name}` | {kind} | {default} | {desc} |")
            out.append("")
        if e["returns"]:
            out.append(f"**Returns** {e['returns']}\n")
        if e["ports"]:
            links = ", ".join(f"[{p}](https://docs.typesafe.ai/{p.split('#')[0]})" for p in e["ports"].split(", "))
            out.append(f"**Ports** {links}\n")
        row = e["live"]
        if row:
            out.append(
                f"**Measured** {row['date']}, {row['model']}: Jev {row['jev_correct']}/{row['cases']}, "
                f"baseline {row['baseline_correct']}/{row['cases']}, {row['calls']} calls, "
                f"{row['input_tokens']:,} input tokens, ${row['cost_usd']:.6f}, mean {round(row['mean_ms'])} ms. "
                f"[Details](../measured/index.md).\n"
            )
    return "\n".join(out)


def on_page_markdown(markdown: str, page, config, files) -> str:  # noqa: ANN001 - mkdocs signature
    """Expand ``{{tools_index}}`` and ``{{tools_ref:<group>}}``."""
    if _INDEX.search(markdown):
        markdown = _INDEX.sub(lambda _m: index_markdown(), markdown)

    def _group(match: re.Match[str]) -> str:
        group = match.group(1)
        if group not in _GROUPS:
            log.warning("%s: unknown tools group {{tools_ref:%s}}", page.file.src_path, group)
            return match.group(0)
        return group_markdown(group)

    return _GROUP.sub(_group, markdown)


if __name__ == "__main__":
    print(index_markdown())
    for name in _GROUPS:
        print(f"\n# {name}\n")
        print(group_markdown(name))
