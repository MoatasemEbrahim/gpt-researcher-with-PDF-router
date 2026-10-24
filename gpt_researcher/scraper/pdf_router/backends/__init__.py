"""Backend registry: one backend per tier. Adding a parser = one file + one entry here + a classify rule."""

from ..types import Tier
from .base import FIGURE_MARKER, PageBackend
from .docling import DoclingBackend
from .llm_markdown import LlmMarkdownBackend, scan_ocr_available
from .pymupdf_text import PlainBackend, TablesBackend

BACKENDS: dict[Tier, PageBackend] = {
    Tier.PLAIN: PlainBackend(),
    Tier.TABLES: TablesBackend(),
    Tier.LAYOUT: LlmMarkdownBackend(),
    Tier.DOCLING: DoclingBackend(),
}

__all__ = ["BACKENDS", "FIGURE_MARKER", "PageBackend", "scan_ocr_available"]
