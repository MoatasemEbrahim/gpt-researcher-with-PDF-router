"""Per-page signals for routing: one text extraction, image info, and PyMuPDF's layout model.

Definitions and thresholds come from probing the fixtures with
tests/pdf_router/tools/probe.py (see DECISIONS.md).
"""

import logging

import pymupdf

from .classify import is_scan
from .types import PageSignals

logger = logging.getLogger(__name__)

MIN_COLUMN_LINE_WIDTH = 40  # points; shorter lines (page numbers, labels) say nothing about columns

_warned_no_layout = False


def compute_signals(page: pymupdf.Page) -> PageSignals:
    # TEXTFLAGS_TEXT leaves image data out of the result, which matters on scans.
    blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
    lines = []  # (bbox, text, horizontal)
    for block in blocks:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                lines.append((pymupdf.Rect(line["bbox"]), text, abs(line["dir"][1]) <= 0.1))

    all_text = "\n".join(text for _bbox, text, _horizontal in lines)
    horizontal = [bbox for bbox, _text, is_horizontal in lines if is_horizontal]
    chars, img_cover = len(all_text), image_coverage(page)
    # The layout model costs ~140 ms a page and finds nothing on an image-only scan.
    tables, pictures = (0, 0) if is_scan(chars, img_cover) else layout_regions(page)
    return PageSignals(
        chars=chars,
        img_cover=img_cover,
        garbage=garbage_ratio(all_text),
        back_jump_ratio=back_jump_ratio(horizontal, page.rect.width / 2),
        tables=tables,
        pictures=pictures,
    )


def image_coverage(page: pymupdf.Page) -> float:
    """Share of the page area covered by images (0.0 to 1.0)."""
    page_area = page.rect.width * page.rect.height
    covered = 0.0
    for info in page.get_image_info():
        box = pymupdf.Rect(info["bbox"]) & page.rect  # clip to the page
        covered += box.width * box.height
    return min(covered / page_area, 1.0) if page_area else 0.0


def garbage_ratio(text: str) -> float:
    """Share of characters that signal a broken text layer."""
    if not text:
        return 0.0
    bad = text.count("�") + text.count("(cid:") * 5
    return bad / len(text)


def back_jump_ratio(line_boxes: list[pymupdf.Rect], middle: float) -> float:
    """Share of column lines where stored order jumps from the right column back to the left.

    Works on lines, not blocks: MuPDF merges interleaved rows into full-width
    blocks, which hides the problem. Lines spanning the middle are ignored.
    """
    sides = []
    for bbox in line_boxes:
        if bbox.width < MIN_COLUMN_LINE_WIDTH:
            continue
        if bbox.x1 < middle:
            sides.append("L")
        elif bbox.x0 > middle:
            sides.append("R")
    jumps = sum(1 for prev, cur in zip(sides, sides[1:]) if prev == "R" and cur == "L")
    return jumps / len(sides) if sides else 0.0


def layout_regions(page: pymupdf.Page) -> tuple[int, int]:
    """(tables, pictures) found by PyMuPDF's layout model. The result stays on page.layout_information."""
    global _warned_no_layout
    page.get_layout()  # a no-op when the pymupdf-layout package is missing
    regions = getattr(page, "layout_information", None)
    if regions is None:
        if not _warned_no_layout:
            logger.warning("PyMuPDF layout model unavailable: tables and figures will not be detected")
            _warned_no_layout = True
        return 0, 0
    labels = [region[-1] for region in regions]
    return labels.count("table"), labels.count("picture")
