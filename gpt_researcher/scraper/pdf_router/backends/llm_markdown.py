"""Tier 2: pymupdf4llm in layout mode (reading order, headings, OCR for scans).

pymupdf4llm is optional, so it's imported inside parse(), never at module level.
"""

import contextlib
import importlib.util
import io
import logging
import re

import pymupdf

from ..types import Tier
from .base import FIGURE_MARKER

# With embed_images=True, pymupdf4llm writes each figure as an inline image
# exactly where it sits on the page; we swap that for the marker.
INLINE_IMAGE = re.compile(r"!\[[^\]]*\]\(data:[^)]*\)")


def scan_ocr_available() -> bool:
    """Whether pymupdf4llm will find an OCR engine (mirrors its select_ocr_function).

    Without one it returns no text for scans, without an error.
    """
    if importlib.util.find_spec("rapidocr") or importlib.util.find_spec("rapidocr_onnxruntime"):
        return True
    try:
        return bool(pymupdf.get_tessdata())
    except Exception:  # raised when no Tesseract language data is found
        return False


class LlmMarkdownBackend:
    name = "pymupdf4llm"
    tier = Tier.LAYOUT

    def available(self) -> bool:
        return importlib.util.find_spec("pymupdf4llm") is not None

    def parse(self, pdf: bytes, pages: list[int]) -> dict[int, str]:
        import pymupdf4llm

        pymupdf4llm.use_layout(True)
        # Its parser messages go through pymupdf.message(); keep them out of the output.
        pymupdf.set_messages(pylogging=True, pylogging_level=logging.DEBUG)
        with pymupdf.open(stream=pdf, filetype="pdf") as doc, contextlib.redirect_stdout(io.StringIO()):
            chunks = pymupdf4llm.to_markdown(
                doc,
                pages=pages,
                page_chunks=True,
                force_text=False,  # drop the text inside figures
                embed_images=True,  # ...and mark where they were (replaced below)
                show_progress=False,
            )
        return {
            chunk["metadata"]["page_number"] - 1: INLINE_IMAGE.sub(FIGURE_MARKER, chunk["text"]).strip()
            for chunk in chunks
        }
