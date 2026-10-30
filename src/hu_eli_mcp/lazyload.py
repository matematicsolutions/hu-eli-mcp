"""Reconstruct NJT legislation with HTML content deferred to AJAX blocks.

Long NJT pages contain real text followed by placeholder containers. The
browser fills those placeholders using POST /ajax/njtGetBlock.json when scrolled.
The initial ELI response alone is therefore not necessarily the full law.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass(frozen=True)
class DeferredBlock:
    element_id: str
    first: int
    last: int
    show_order: int
    last_show_order: int | None

    def request_item(self) -> dict[str, int]:
        item = {"start": self.show_order}
        if self.last_show_order is not None:
            item["last"] = self.last_show_order
        return item


@dataclass(frozen=True)
class DeferredGroup:
    blocks: tuple[DeferredBlock, ...]

    @property
    def first(self) -> int:
        return self.blocks[0].first

    @property
    def last(self) -> int:
        return self.blocks[-1].last

    def request_items(self) -> list[dict[str, int]]:
        return [block.request_item() for block in self.blocks]


class _PlaceholderParser(HTMLParser):
    """Track the exact character offsets of deferred outer div elements."""

    def __init__(self, markup: str):
        super().__init__(convert_charrefs=False)
        self._markup = markup
        self._line_offsets = [0] + [m.end() for m in re.finditer("\n", markup)]
        self._div_stack: list[tuple[str, int, int, int | None] | None] = []
        self.blocks: list[DeferredBlock] = []
        # div elements that look like NJT block markup but are not the known placeholder form
        self.unrecognized = 0

    def unclosed_placeholders(self) -> list[str]:
        return [item[0] for item in self._div_stack if item is not None]

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return

        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if {"pH", "borderStart"} <= classes:
            element_id = attributes.get("id")
            start = attributes.get("data-show-order")
            last = attributes.get("data-last-show-order")
            if not element_id or start is None:
                raise ValueError("NJT deferred block is missing its ID or show-order.")
            self._div_stack.append(
                (element_id, self._offset(), int(start), int(last) if last else None)
            )
        else:
            if "borderStart" in classes:
                self.unrecognized += 1
            self._div_stack.append(None)

    def handle_endtag(self, tag: str) -> None:
        if tag != "div" or not self._div_stack:
            return
        item = self._div_stack.pop()
        if item is not None:
            element_id, first, start, last = item
            closing_end = self._markup.find(">", self._offset()) + 1
            if closing_end <= 0:
                raise ValueError("Unterminated NJT deferred block.")
            self.blocks.append(
                DeferredBlock(element_id, first, closing_end, start, last)
            )


_NON_TEXT = re.compile(r"<!--.*?-->|<[^>]*>|&nbsp;|&#160;|&#xa0;|\s+", re.DOTALL | re.IGNORECASE)


def _visible_text(fragment: str) -> str:
    return _NON_TEXT.sub("", fragment)


def find_deferred_groups(markup: str) -> list[DeferredGroup]:
    """Group adjacent block placeholders; keep real HTML between groups intact."""
    parser = _PlaceholderParser(markup)
    parser.feed(markup)
    parser.close()
    blocks = sorted(parser.blocks, key=lambda block: block.first)

    # A changed NJT markup should not silently be interpreted as a full text. Only
    # inspect div class attributes: "borderStart" in inline CSS/JS or "pH" in legal
    # text (e.g. "pH-érték") must not make a short, complete document fail.
    if parser.unrecognized:
        raise ValueError("NJT deferred-block markup is not recognized.")

    # A placeholder whose closing tag never arrives would otherwise be skipped silently.
    unclosed = parser.unclosed_placeholders()
    if unclosed:
        raise ValueError(f"Unclosed NJT deferred block(s): {unclosed[:3]}")

    # Placeholders are empty by definition. Rendered text inside a computed placeholder
    # range means the div boundaries were mis-detected (unbalanced HTML), and replacing
    # that range would silently delete real legal text.
    for block in blocks:
        if _visible_text(markup[block.first : block.last]):
            raise ValueError(
                f"NJT deferred block {block.element_id} unexpectedly contains rendered text."
            )

    groups: list[list[DeferredBlock]] = []
    for block in blocks:
        if groups:
            between = markup[groups[-1][-1].last : block.first]
            if not re.sub(r"<!--.*?-->|\s+", "", between, flags=re.DOTALL):
                groups[-1].append(block)
                continue
        groups.append([block])

    return [DeferredGroup(tuple(items)) for items in groups]


_SLICE_ID = re.compile(r'id="(sc[^"]*?)-(\d+)"')


def _slice_numbers(markup: str) -> dict[str, set[int]]:
    """NJT content-slice ids ``sc{document-id}-{n}`` grouped by document prefix."""
    found: dict[str, set[int]] = {}
    for prefix, number in _SLICE_ID.findall(markup):
        found.setdefault(prefix, set()).add(int(number))
    return found


def _range_returned(placeholder: str, returned: dict[str, set[int]]) -> bool:
    """Whether the response has content slices inside the placeholder's id range.

    NJT does not always echo the outer placeholder id (seen for an annex group of
    314/2012. Korm. rendelet), but its slice ids are sequential, and the placeholder's
    own children carry the first and last id of the range it stands for.
    """
    own = _slice_numbers(placeholder)
    for prefix, numbers in own.items():
        low, high = min(numbers), max(numbers)
        if any(low <= n <= high for n in returned.get(prefix, ())):
            return True
    return False


def merge_deferred_groups(
    markup: str, groups: list[DeferredGroup], fragments: list[str]
) -> str:
    """Replace each run of placeholders with the matching server HTML."""
    if len(groups) != len(fragments):
        raise ValueError("Not all NJT deferred groups were downloaded.")

    for group, fragment in reversed(list(zip(groups, fragments, strict=True))):
        returned = _slice_numbers(fragment)
        missing = [
            block.element_id for block in group.blocks
            if f'id="{block.element_id}"' not in fragment
            and not _range_returned(markup[block.first : block.last], returned)
        ]
        if missing:
            raise ValueError(f"NJT omitted expected deferred-block IDs: {missing[:3]}")
        markup = markup[: group.first] + fragment + markup[group.last :]

    if find_deferred_groups(markup):
        raise ValueError("Deferred NJT blocks remain after reconstruction.")
    return markup
