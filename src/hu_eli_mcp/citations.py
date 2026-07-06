"""HTML parsing + citation helpers for Nemzeti Jogszabalytar (njt.jog.gov.hu).

NJT serves each document as a server-rendered HTML page (no JSON/XML API). We parse the
handful of stable markup landmarks with the stdlib ``html.parser`` - no third-party HTML
dependency:

- ``<h1 class="... jogszabalyMainTitle ...">`` - the citation-style number, e.g.
  "2013. evi V. torveny".
- ``<h2 class="... jogszabalySubtitle ...">`` - the subject of the act, e.g.
  "a Polgari Torvenykonyvrol".
- ``<div class="hataly">`` - the "hatalyos" (in force) as-of date shown on the page, if present.
- ``<table class="table table-bordered table-condensed table-hover">`` on the code-list pages
  (``/eli/tipuskodok``, ``/eli/kibocsatokodok``) - a plain two-column ``code -> name`` table.

Citation contract (Art. IV CONSTITUTION):
- ``eli_uri``: the native ELI URI the caller resolved, e.g.
  ``https://njt.jog.gov.hu/eli/TV/2013/5``. Hungary has published a genuine, documented
  national ELI implementation since 2023 - this is a real ELI, never a fabricated one.
- ``human_readable_citation``: the official citation, built from the parsed title + subtitle,
  e.g. "2013. evi V. torveny (a Polgari Torvenykonyvrol)".
- ``source_url``: the resolved, browsable ``njt.jog.gov.hu/jogszabaly/...`` document page.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any


def _class_list(attrs: list[tuple[str, str | None]]) -> set[str]:
    for key, value in attrs:
        if key == "class" and value:
            return set(value.split())
    return set()


class _DocumentParser(HTMLParser):
    """Extracts the main title, subtitle and in-force marker from a jogszabaly page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.subtitle: str | None = None
        self.in_force_date: str | None = None
        self._capture: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = _class_list(attrs)
        if tag == "h1" and "jogszabalyMainTitle" in classes and self.title is None:
            self._capture = "title"
            self._buffer = []
        elif tag == "h2" and "jogszabalySubtitle" in classes and self.subtitle is None:
            self._capture = "subtitle"
            self._buffer = []
        elif tag == "div" and "hataly" in classes and self.in_force_date is None:
            self._capture = "hataly"
            self._buffer = []
        elif tag == "sup" and self._capture in {"title", "subtitle"}:
            # Footnote markers (<sup class="fnSup">N</sup>) are not part of the citation.
            self._capture = f"_skip_{self._capture}"

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "div"} and self._capture in {"title", "subtitle", "hataly"}:
            text = "".join(self._buffer).strip()
            if self._capture == "title":
                self.title = text or None
            elif self._capture == "subtitle":
                self.subtitle = text or None
            elif self._capture == "hataly":
                self.in_force_date = text or None
            self._capture = None
            self._buffer = []
        elif tag == "sup" and self._capture and self._capture.startswith("_skip_"):
            self._capture = self._capture.removeprefix("_skip_")

    def handle_data(self, data: str) -> None:
        if self._capture in {"title", "subtitle", "hataly"}:
            self._buffer.append(data)


def parse_document_page(html: str) -> dict[str, Any]:
    """Parse a ``/jogszabaly/{doc_id}`` page into title / subtitle / in_force_date."""
    parser = _DocumentParser()
    parser.feed(html)
    out: dict[str, Any] = {}
    if parser.title:
        out["title"] = parser.title
    if parser.subtitle:
        out["subtitle"] = parser.subtitle
    if parser.in_force_date:
        out["in_force_date"] = parser.in_force_date
    return out


def human_readable_citation(title: str | None, subtitle: str | None) -> str | None:
    """Build the official-style citation: '{title} ({subtitle})' when both are present."""
    if not title:
        return None
    if subtitle:
        return f"{title} ({subtitle})"
    return title


class _CodeTableParser(HTMLParser):
    """Extracts rows of a simple two-column code -> name table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cells: list[str] = []
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = _class_list(attrs)
        if tag == "table" and {"table-bordered", "table-condensed"} <= classes:
            self._in_table = True
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._cells = []
        elif tag == "td" and self._in_row:
            self._in_cell = True
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._in_table = False
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if len(self._cells) >= 2:
                code, name = self._cells[0].strip(), self._cells[1].strip()
                if code:
                    self.rows.append((code, name))
        elif tag == "td" and self._in_cell:
            self._in_cell = False
            self._cells.append("".join(self._buffer))

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._buffer.append(data)


def parse_code_table(html: str) -> list[tuple[str, str]]:
    """Parse a code -> name table from /eli/tipuskodok or /eli/kibocsatokodok."""
    parser = _CodeTableParser()
    parser.feed(html)
    return parser.rows
