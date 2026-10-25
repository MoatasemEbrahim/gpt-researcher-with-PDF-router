"""Tier 3: Docling (OCR, broken text layers, final fallback).

Docling is optional and slow to start, so it's imported lazily and one
converter is kept per process.
"""

import importlib.util
import io

import pymupdf

from ..types import Tier
from .base import FIGURE_MARKER

_converter = None


def _get_converter():
    global _converter
    if _converter is None:
        from docling.document_converter import DocumentConverter

        _converter = DocumentConverter()
    return _converter


class DoclingBackend:
    name = "docling"
    tier = Tier.DOCLING

    def available(self) -> bool:
        return importlib.util.find_spec("docling") is not None

    def parse(self, path: str, pages: list[int]) -> dict[int, str]:
        from docling.datamodel.base_models import DocumentStream

        # One Docling call for all the pages, even when they aren't contiguous.
        with pymupdf.open(path) as doc, pymupdf.open() as subset:
            for number in pages:
                subset.insert_pdf(doc, from_page=number, to_page=number)
            subset_pdf = subset.tobytes()
        result = _get_converter().convert(DocumentStream(name="pages.pdf", stream=io.BytesIO(subset_pdf)))
        return {
            number: result.document.export_to_markdown(page_no=position, image_placeholder=FIGURE_MARKER).strip()
            for position, number in enumerate(pages, start=1)  # Docling numbers pages from 1
        }
