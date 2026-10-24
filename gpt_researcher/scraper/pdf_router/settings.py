"""Router settings from environment variables, read at call time (like the other scrapers do)."""

import os


def enabled() -> bool:
    """PDF_ROUTER_ENABLED=false falls back to the legacy single-extractor path."""
    return os.environ.get("PDF_ROUTER_ENABLED", "true").strip().lower() not in ("false", "0", "no")


def max_workers() -> int:
    """Processes in the shared pool (signals, tiers 0-2).

    Measured per worker: ~260 MB after start-up, ~650 MB after parsing, ~1.2 GB once it has run OCR.
    """
    return int(os.environ.get("PDF_ROUTER_MAX_WORKERS", min(4, os.cpu_count() or 1)))


def docling_concurrency() -> int:
    """Docling jobs running at once, across all PDFs. Docling is memory-heavy."""
    return int(os.environ.get("PDF_ROUTER_DOCLING_CONCURRENCY", "1"))


def doc_timeout_s() -> float:
    """Time budget for one PDF. When it runs out, finished pages are returned and the rest are marked."""
    return float(os.environ.get("PDF_ROUTER_DOC_TIMEOUT_S", "120"))
