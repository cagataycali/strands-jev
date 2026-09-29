"""mkdocs hook: the house rules for the hand-written pages, enforced at build time.

Three checks, each a ``log.warning`` that ``mkdocs build --strict`` turns into a failed build:

* no em dash or en dash in any page under ``docs/`` this site writes (the files pulled in
  from the package, ``docs/DESIGN.md``, ``CHANGELOG.md`` and ``tests/live/RESULTS.md``, are
  the package's and are not checked here);
* a site word ceiling over the hand-written pages: the sum of ``wc -w`` over every ``.md``
  under ``docs/`` except the generated Tools pages and the pages that are only a snippet
  include. The ceiling is ``WORD_CEILING``; raising it is a deliberate edit to this file;
* no ``{{`` left in a rendered page, which is a hook token that nobody expanded.

``python docs/hooks/house_style.py`` prints the word count per page and the total.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

log = logging.getLogger("mkdocs.hooks.house_style")

DOCS = Path(__file__).resolve().parents[1]
WORD_CEILING = 9_000
DASHES = re.compile("[\u2013\u2014]")
GENERATED = re.compile(r"^\{\{\s*(tools_index|tools_ref:[a-z_]+)\s*\}\}\s*$", re.M)
SNIPPET = re.compile(r"^--8<--\s+\"", re.M)
TOKEN = re.compile(r"\{\{\s*(?:n:|tools_)[^}]*\}\}")


def pages() -> list[Path]:
    return sorted(p for p in DOCS.rglob("*.md") if "hooks" not in p.parts and p.name != "DESIGN.md")


def words(page: Path) -> int:
    """Whitespace-separated tokens, the number ``wc -w`` prints, generated tokens removed."""
    text = GENERATED.sub("", page.read_text(encoding="utf-8"))
    text = SNIPPET.sub("", text)
    return len(text.split())


def check_dashes(page: Path) -> int:
    text = page.read_text(encoding="utf-8")
    hits = 0
    for number, line in enumerate(text.splitlines(), 1):
        if DASHES.search(line):
            hits += 1
            log.warning("%s:%d: em or en dash in prose; write a comma, a colon or a full stop", page.relative_to(DOCS), number)
    return hits


def on_files(files, config):  # noqa: ANN001 - mkdocs signature
    total = 0
    for page in pages():
        check_dashes(page)
        total += words(page)
    if total > WORD_CEILING:
        log.warning("site has %d hand-written words, over the %d ceiling in docs/hooks/house_style.py", total, WORD_CEILING)
    return files


def on_page_content(html: str, page, config, files) -> str:  # noqa: ANN001 - mkdocs signature
    for match in TOKEN.finditer(html):
        log.warning("%s: unexpanded token %s", page.file.src_path, match.group(0))
    return html


if __name__ == "__main__":
    total = 0
    for page in pages():
        n = words(page)
        total += n
        print(f"{n:6}  {page.relative_to(DOCS)}")
    print(f"\n{len(pages())} pages, {total} words, ceiling {WORD_CEILING}")
    sys.exit(1 if total > WORD_CEILING else 0)
