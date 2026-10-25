"""Router settings from environment variables, read at call time (like the other scrapers do)."""

import os


def enabled() -> bool:
    """PDF_ROUTER_ENABLED=false falls back to the legacy single-extractor path."""
    return os.environ.get("PDF_ROUTER_ENABLED", "true").strip().lower() not in ("false", "0", "no")


def max_workers() -> int:
    """Processes in the shared pool (signals, tiers 0-2).

    Measured per worker: ~260 MB after start-up, ~650-870 MB after parsing text PDFs, ~830-900 MB once it has also run OCR.
    """
    return int(os.environ.get("PDF_ROUTER_MAX_WORKERS", min(4, os.cpu_count() or 1)))


def worker_max_tasks() -> int | None:
    """Tasks a shared worker runs before it's replaced (0 = never).

    Replacing a worker releases memory that Python and the native libraries never hand back.
    A restart costs ~1.2 s (re-importing the package) plus the model load.
    """
    return int(os.environ.get("PDF_ROUTER_WORKER_MAX_TASKS", "200")) or None


def docling_concurrency() -> int:
    """Docling jobs running at once, across all PDFs. Docling is memory-heavy."""
    return int(os.environ.get("PDF_ROUTER_DOCLING_CONCURRENCY", "1"))


def max_pages() -> int | None:
    """Pages routed per PDF, from PDF_ROUTER_MAX_PAGES (default 200; 0 = all of them).

    Classification costs ~150 ms a page, so 200 pages is ~8 s of pool time with 4 workers.
    The pages past the limit are left out, and one marker at the end says so.
    """
    return int(os.environ.get("PDF_ROUTER_MAX_PAGES", "200")) or None


def doc_timeout_s() -> float:
    """Time budget for one PDF. When it runs out, finished pages are returned and the rest are marked."""
    return float(os.environ.get("PDF_ROUTER_DOC_TIMEOUT_S", "120"))
