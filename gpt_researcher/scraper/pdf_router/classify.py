"""Pick a starting tier for a page from its signals. Rules are checked in order; the first match wins."""

from .types import PageSignals, Tier

# Scanned page: almost no text and mostly image. Fixture scans: chars 0, cover 1.0.
SCAN_MAX_CHARS = 50
SCAN_MIN_IMG_COVER = 0.5
# Broken text layer (replacement chars, "(cid:" codes). Not in the fixtures; untested on real PDFs.
GARBAGE_MIN = 0.05
# Text stored out of reading order. Out-of-order fixture 0.34; real papers at most 0.10.
BACK_JUMP_MIN = 0.15


def is_scan(chars: int, img_cover: float) -> bool:
    return chars < SCAN_MAX_CHARS and img_cover >= SCAN_MIN_IMG_COVER


def classify(signals: PageSignals, *, scan_ocr_available: bool) -> Tier:
    """Return the cheapest tier expected to handle the page.

    scan_ocr_available: whether the LAYOUT tier (pymupdf4llm) has an OCR
    engine. If it does, scans go there; otherwise to Docling.
    Figures don't change the tier: every tier replaces figure text with a marker.
    """
    if is_scan(signals.chars, signals.img_cover):
        return Tier.LAYOUT if scan_ocr_available else Tier.DOCLING
    if signals.garbage >= GARBAGE_MIN:
        return Tier.DOCLING
    if signals.back_jump_ratio >= BACK_JUMP_MIN:
        return Tier.LAYOUT
    if signals.tables:
        return Tier.TABLES
    return Tier.PLAIN
