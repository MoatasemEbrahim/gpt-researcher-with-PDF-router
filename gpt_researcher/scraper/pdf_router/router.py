"""route_pdf(): classify every page, parse it with the cheapest backend that can handle it, merge in order.

Stage 1 runs in the shared pool, a chunk of pages per task: signals, classify, and
tiers 0-1 rendered right away (the page and its layout result are already there).
Stage 2 sends the remaining pages on: tier 2 to the shared pool, all tier-3 pages
to Docling in one call. A failure, timeout or missing backend moves a page down the
FALLBACK chain. Everything is bounded by the document time budget.
"""

import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, BrokenExecutor, Executor, Future, wait
from dataclasses import dataclass, field

import pymupdf

from . import executors, settings
from .backends import BACKENDS, scan_ocr_available
from .backends.pymupdf_text import render_page
from .classify import classify
from .signals import compute_signals
from .types import PageOutcome, RouterResult, Tier

logger = logging.getLogger(__name__)

# Pages per worker task. Measured warm with 4 workers (RoBERTa 13 pp / BERT 16 pp):
# 4 -> 3.0 / 2.4 s, 2 -> 1.9 / 1.8 s, 1 -> 1.8 / 1.8 s. 2 keeps nearly all the gain
# and sends half as many copies of the PDF to the workers.
CHUNK_PAGES = 2
DOCLING_TIMEOUT_BASE_S = 30.0
DOCLING_TIMEOUT_PER_PAGE_S = 10.0
# Where a page goes when its tier fails, times out or isn't installed: only ever down the ladder.
FALLBACK = {Tier.DOCLING: Tier.LAYOUT, Tier.LAYOUT: Tier.PLAIN, Tier.TABLES: Tier.PLAIN, Tier.PLAIN: None}

# PyMuPDF isn't thread-safe, and the scraper calls route_pdf() from many threads.
MUPDF_LOCK = threading.Lock()


def route_pdf(pdf: bytes, source_url: str) -> RouterResult:
    """Markdown for the whole PDF, pages in order. Raises if the PDF can't be opened at all."""
    started = time.perf_counter()
    with MUPDF_LOCK, pymupdf.open(stream=pdf, filetype="pdf") as doc:
        page_count = doc.page_count
        title = (doc.metadata or {}).get("title") or ""

    run = _Run(pdf, page_count, deadline=started + settings.doc_timeout_s())
    run.run()
    result = RouterResult(markdown=run.markdown(), title=title, pages=run.outcomes())
    _log_summary(source_url, result, (time.perf_counter() - started) * 1000)
    return result


@dataclass
class _Page:
    number: int
    planned: Tier = Tier.PLAIN
    markdown: str = ""
    backend: str = ""
    ms: float = 0.0
    reasons: list[str] = field(default_factory=list)  # one per tier that didn't work


@dataclass
class _Job:
    tier: Tier | None  # None = stage 1
    numbers: list[int]
    pool: Executor | None
    submitted: float


class _Run:
    """The state of one route_pdf() call."""

    def __init__(self, pdf: bytes, page_count: int, deadline: float):
        self.pdf = pdf
        self.deadline = deadline
        self.available = {tier: backend.available() for tier, backend in BACKENDS.items()}
        self.ocr = self.available[Tier.LAYOUT] and scan_ocr_available()
        self.pages = [_Page(number) for number in range(page_count)]
        self.jobs: dict[Future, _Job] = {}
        self.stage1_left = 0
        self.docling_numbers: list[int] = []

    def run(self) -> None:
        for numbers in _chunks(range(len(self.pages))):
            self._submit(None, numbers, _stage1, self.pdf, numbers, self.ocr)
            self.stage1_left += 1
        while True:
            # Docling gets one call per PDF, so it waits until every page is classified.
            if not self.stage1_left and self.docling_numbers:
                numbers, self.docling_numbers = sorted(self.docling_numbers), []
                future = executors.docling_waiters().submit(_run_docling, self.pdf, numbers, self.deadline)
                self.jobs[future] = _Job(Tier.DOCLING, numbers, None, time.perf_counter())
            remaining = self.deadline - time.perf_counter()
            if not self.jobs or remaining <= 0:
                break
            done, _ = wait(self.jobs, timeout=remaining, return_when=FIRST_COMPLETED)
            for future in done:
                self._finished(future, self.jobs.pop(future))
        # Out of time: pages still in flight are marked; their tasks are left to finish.
        in_flight = set(self.docling_numbers)
        for future, job in self.jobs.items():
            future.cancel()  # only stops tasks that haven't started; see weak spots
            in_flight.update(job.numbers)
        for number in sorted(in_flight):
            if not self.pages[number].markdown:
                self.pages[number].reasons.append("document time budget exceeded")

    def _submit(self, tier: Tier | None, numbers: list[int], fn, *args) -> None:
        pool = executors.shared_pool()
        self.jobs[pool.submit(fn, *args)] = _Job(tier, numbers, pool, time.perf_counter())

    def _finished(self, future: Future, job: _Job) -> None:
        if job.tier is None:
            self.stage1_left -= 1
        try:
            output = future.result()
        except Exception as error:
            if isinstance(error, BrokenExecutor) and job.pool is not None:
                executors.reset_shared_pool(job.pool)  # a worker crashed; the next submit gets a new pool
            reason = f"{type(error).__name__}: {error}"
            if job.tier is None:
                for number in job.numbers:
                    self.pages[number].reasons.append(f"classification: {reason}")
                self._assign(job.numbers, Tier.PLAIN)
            else:
                self._fall_back(job.numbers, job.tier, reason)
            return

        if job.tier is None:
            later = defaultdict(list)
            for number, tier, markdown, ms, error in output:
                page = self.pages[number]
                page.planned = tier
                if markdown:
                    page.markdown, page.backend, page.ms = markdown, BACKENDS[tier].name, ms
                elif tier <= Tier.TABLES:
                    self._fall_back([number], tier, error or "empty output")
                else:
                    later[tier].append(number)
            for tier, numbers in later.items():
                self._assign(numbers, tier)
            return

        per_page_ms = (time.perf_counter() - job.submitted) * 1000 / len(job.numbers)
        for number in job.numbers:
            markdown = output.get(number, "")
            if markdown.strip():
                page = self.pages[number]
                page.markdown, page.backend, page.ms = markdown, BACKENDS[job.tier].name, per_page_ms
            else:
                self._fall_back([number], job.tier, "empty output")

    def _fall_back(self, numbers: list[int], tier: Tier, reason: str) -> None:
        for number in numbers:
            self.pages[number].reasons.append(f"{BACKENDS[tier].name}: {reason}")
        if FALLBACK[tier] is not None:
            self._assign(numbers, FALLBACK[tier])

    def _assign(self, numbers: list[int], tier: Tier) -> None:
        """Send pages to a tier, or down the chain to the first one that's installed."""
        while not self.available[tier]:
            for number in numbers:
                self.pages[number].reasons.append(f"{BACKENDS[tier].name}: not installed")
            tier = FALLBACK[tier]  # PLAIN is always available, so this ends
        if tier is Tier.DOCLING:
            self.docling_numbers += numbers
            return
        for chunk in _chunks(numbers):
            self._submit(tier, chunk, _parse, tier, self.pdf, chunk)

    def markdown(self) -> str:
        if not any(page.markdown for page in self.pages):
            return ""  # a dead PDF must not look alive to the scraper's length check
        return "\n\n".join(page.markdown or _marker(page) for page in self.pages)

    def outcomes(self) -> list[PageOutcome]:
        return [
            PageOutcome(
                page=page.number,
                tier_planned=page.planned,
                backend_used=page.backend,
                ms=round(page.ms, 1),
                status="failed" if not page.markdown else "fallback" if page.reasons else "ok",
                reason="; ".join(page.reasons),
            )
            for page in self.pages
        ]


def _stage1(pdf: bytes, numbers: list[int], scan_ocr_available: bool) -> list[tuple]:
    """Worker: (page, tier, markdown or None, ms, error) per page; tiers 0-1 rendered here."""
    results = []
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        for number in numbers:
            start = time.perf_counter()
            page = doc[number]
            tier = classify(compute_signals(page), scan_ocr_available=scan_ocr_available)
            markdown, error = None, ""
            if tier <= Tier.TABLES:
                try:
                    markdown = render_page(page, tables=tier is Tier.TABLES)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
            results.append((number, tier, markdown, (time.perf_counter() - start) * 1000, error))
    return results


def _parse(tier: Tier, pdf: bytes, numbers: list[int]) -> dict[int, str]:
    """Worker: one backend over a chunk of pages."""
    return BACKENDS[tier].parse(pdf, numbers)


def _run_docling(pdf: bytes, numbers: list[int], deadline: float) -> dict[int, str]:
    """Waiter thread: take a Docling slot, run the job, and stop the pool if it times out.

    The job's timeout starts once it holds a slot, not while it waits for one.
    """
    slot = executors.docling_slot()
    if not slot.acquire(timeout=max(0.0, deadline - time.perf_counter())):
        raise TimeoutError("no free Docling slot before the time budget ran out")
    try:
        pool = executors.docling_pool()
        future = pool.submit(_parse, Tier.DOCLING, pdf, numbers)
        timeout = DOCLING_TIMEOUT_BASE_S + DOCLING_TIMEOUT_PER_PAGE_S * len(numbers)
        timeout = max(0.0, min(timeout, deadline - time.perf_counter()))
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            executors.reset_docling_pool(pool)  # the only way to stop a running job
            raise TimeoutError(f"Docling took more than {timeout:.1f} s") from None
        except BrokenExecutor:
            executors.reset_docling_pool(pool)
            raise
    finally:
        slot.release()


def _chunks(numbers) -> list[list[int]]:
    numbers = list(numbers)
    return [numbers[i : i + CHUNK_PAGES] for i in range(0, len(numbers), CHUNK_PAGES)]


def _marker(page: _Page) -> str:
    reason = page.reasons[-1] if page.reasons else "unknown"
    reason = reason.replace("--", "-")[:120]  # "--" would end the HTML comment early
    return f"<!-- page {page.number + 1}: not extracted ({reason}) -->"


def _log_summary(source_url: str, result: RouterResult, total_ms: float) -> None:
    pages, ms = defaultdict(int), defaultdict(float)
    for outcome in result.pages:
        name = outcome.backend_used or "none"
        pages[name] += 1
        ms[name] += outcome.ms
    tiers = ", ".join(f"{name} {pages[name]} p / {ms[name]:.0f} ms" for name in sorted(pages))
    fallbacks = sum(outcome.status == "fallback" for outcome in result.pages)
    failed = sum(outcome.status == "failed" for outcome in result.pages)
    logger.info(
        f"PDF router: {source_url}: {len(result.pages)} pages in {total_ms:.0f} ms ({tiers}); "
        f"fallbacks {fallbacks}, failed {failed}"
    )
