"""Tiers 0 and 1: PyMuPDF text, plus find_tables() Markdown for tier 1.

Both share render_page(), which works on an open page so the worker that
classified the page can reuse its layout-model result.
"""

from collections import Counter
from contextlib import contextmanager

import pymupdf

from ..types import Tier
from .base import FIGURE_MARKER

# Expand ligatures ("ﬁ" -> "fi"). TEXT_DEHYPHENATE only works in "text" mode,
# so _join_lines() joins hyphenated line ends itself.
TEXT_FLAGS = pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES


def render_page(page: pymupdf.Page, *, tables: bool) -> str:
    """Page Markdown: paragraphs in stored order, figures as a marker, and (tier 1) tables as Markdown.

    A region (table or figure) is written once, at the first of: the first line
    inside it, or the first block below it in the same column. Lines inside a
    region are dropped.
    """
    if getattr(page, "layout_information", None) is None and hasattr(page, "get_layout"):
        page.get_layout()  # not classified in this process yet (e.g. a fallback)
    regions = []  # (rect, markdown)
    if tables:
        with _reuse_layout(page):
            found = page.find_tables().tables
        # fill_empty=False: a section row like "Our reimplementation (with NSP loss):"
        # isn't copied into every empty cell. to_markdown() is most of tier 1's cost
        # (~300 ms a table page); extract() is fast but drops decimal points.
        regions += [(pymupdf.Rect(t.bbox), t.to_markdown(fill_empty=False).strip()) for t in found]
    regions += [
        (pymupdf.Rect(box[:4]), FIGURE_MARKER) for box in page.layout_information or [] if box[-1] == "picture"
    ]

    parts = []
    emitted = set()

    def emit(index):
        if index not in emitted:
            emitted.add(index)
            parts.append(regions[index][1])

    blocks = page.get_text("dict", flags=TEXT_FLAGS)["blocks"]
    direction = _dominant_direction(blocks)
    for block in blocks:
        block_rect = pymupdf.Rect(block["bbox"])
        for index, (rect, _markdown) in enumerate(regions):
            if rect.y1 <= block_rect.y0 and min(rect.x1, block_rect.x1) > max(rect.x0, block_rect.x0):
                emit(index)
        paragraph = []
        for line in block.get("lines", []):
            if _direction(line) != direction:  # set against the page's text, e.g. the arXiv margin stamp
                continue
            text = "".join(span["text"] for span in line["spans"]).strip()
            if not text:
                continue
            index = _region_of(pymupdf.Rect(line["bbox"]), regions)
            if index is None:
                paragraph.append(text)
                continue
            if paragraph:
                parts.append(_join_lines(paragraph))
                paragraph = []
            emit(index)
        if paragraph:
            parts.append(_join_lines(paragraph))

    for index in range(len(regions)):
        emit(index)
    return "\n\n".join(parts)


def _region_of(line_rect: pymupdf.Rect, regions: list) -> int | None:
    """Index of the region holding the line's centre, if any."""
    centre = pymupdf.Point((line_rect.x0 + line_rect.x1) / 2, (line_rect.y0 + line_rect.y1) / 2)
    for index, (rect, _markdown) in enumerate(regions):
        if rect.contains(centre):
            return index
    return None


def _direction(line: dict) -> tuple[int, int]:
    """A line's writing direction snapped to an axis: (1, 0) left to right, (0, ±1) sideways, (0, 0) diagonal."""
    dx, dy = line["dir"]
    if abs(dy) <= 0.1:
        return (1 if dx >= 0 else -1, 0)
    if abs(dx) <= 0.1:
        return (0, 1 if dy >= 0 else -1)
    return (0, 0)


def _dominant_direction(blocks: list) -> tuple[int, int]:
    """The direction most of the page's characters are written in.

    Lines written in any other direction are dropped. On a normal page that is
    the arXiv margin stamp or a watermark. On a page set sideways (a landscape
    table in a portrait document) it is the page number, and the sideways text,
    which the old rule threw away, is kept.
    """
    chars = Counter()
    for block in blocks:
        for line in block.get("lines", []):
            chars[_direction(line)] += sum(len(span["text"]) for span in line["spans"])
    return max(chars, key=chars.get) if chars else (1, 0)


def _join_lines(lines: list[str]) -> str:
    """Join a block's lines into one paragraph, removing line-end hyphens before a lowercase letter."""
    text = ""
    for line in lines:
        if len(text) > 1 and text.endswith("-") and text[-2].isalpha() and line[:1].islower():
            text = text[:-1] + line
        else:
            text = f"{text} {line}" if text else line
    return text


@contextmanager
def _reuse_layout(page: pymupdf.Page):
    """Let find_tables() reuse the page's layout-model result instead of running the model again.

    find_tables() always calls page.get_layout(), which re-runs the model
    (~140 ms). PyMuPDF has no option for this, so swap its private hook for
    the call. Safe in a worker process, where only one page runs at a time.
    """
    known = getattr(page, "layout_information", None)
    original = pymupdf._get_layout
    if known is None or original is None:
        yield
        return
    pymupdf._get_layout = lambda *args, **kwargs: known
    try:
        yield
    finally:
        pymupdf._get_layout = original


class PlainBackend:
    name = "plain"
    tier = Tier.PLAIN
    tables = False

    def available(self) -> bool:
        return True

    def parse(self, pdf: bytes, pages: list[int]) -> dict[int, str]:
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            return {number: render_page(doc[number], tables=self.tables) for number in pages}


class TablesBackend(PlainBackend):
    name = "pymupdf_tables"
    tier = Tier.TABLES
    tables = True
