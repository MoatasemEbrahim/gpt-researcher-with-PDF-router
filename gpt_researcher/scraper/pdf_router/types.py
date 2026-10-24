"""Shared types for the PDF page router."""

from dataclasses import dataclass
from enum import IntEnum


class Tier(IntEnum):
    """Backend ladder, cheapest first. Integer values so tiers can be compared."""

    PLAIN = 0  # PyMuPDF text
    TABLES = 1  # PyMuPDF text + find_tables() Markdown
    LAYOUT = 2  # pymupdf4llm: reading order, headings, OCR
    DOCLING = 3  # scans without tier-2 OCR, broken text layers, final fallback


@dataclass(frozen=True)
class PageSignals:
    """Per-page measurements the classifier routes on."""

    chars: int
    img_cover: float
    garbage: float
    back_jump_ratio: float
    tables: int  # table regions found by PyMuPDF's layout model
    pictures: int  # figure regions; every tier replaces their text with a marker, so they don't affect the tier
