"""route_pdf(): dispatch, fallback, timeouts, budget and merge.

Most tests swap the process pools for thread pools and the backends for fakes:
threads see the monkeypatched registry, worker processes wouldn't. The last test
runs the real pools on a fixture.
"""

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
import pytest

from gpt_researcher.scraper.pdf_router import Tier, executors, route_pdf, router
from gpt_researcher.scraper.pdf_router.backends import BACKENDS

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pdf"


def _pdf(pages: int) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    return doc.tobytes()


class FakeBackend:
    def __init__(self, name, available=True, fail=False, empty=(), delay=None):
        self.name = name
        self._available = available
        self.fail = fail
        self.empty = set(empty)  # pages that come back empty
        self.delay = delay or {}  # page -> seconds
        self.calls = []

    def available(self):
        return self._available

    def parse(self, pdf, pages):
        self.calls.append(list(pages))
        time.sleep(max((self.delay.get(n, 0) for n in pages), default=0))
        if self.fail:
            raise RuntimeError("boom")
        return {n: "" if n in self.empty else f"{self.name} page {n}" for n in pages}


@pytest.fixture
def fake(monkeypatch):
    """Thread pools, fake backends, and a fake stage 1 that returns PLANNED tiers."""
    state = {"planned": {}, "stage1_fails": False, "resets": 0}
    shared = ThreadPoolExecutor(max_workers=8)
    waiters = ThreadPoolExecutor(max_workers=4)
    docling = {"pool": ThreadPoolExecutor(max_workers=1)}
    slot = threading.Semaphore(1)

    def reset_docling(pool):
        state["resets"] += 1
        docling["pool"] = ThreadPoolExecutor(max_workers=1)

    monkeypatch.setattr(executors, "shared_pool", lambda: shared)
    monkeypatch.setattr(executors, "docling_waiters", lambda: waiters)
    monkeypatch.setattr(executors, "docling_pool", lambda: docling["pool"])
    monkeypatch.setattr(executors, "docling_slot", lambda: slot)
    monkeypatch.setattr(executors, "reset_docling_pool", reset_docling)
    monkeypatch.setattr(router, "scan_ocr_available", lambda: True)

    backends = {
        Tier.PLAIN: FakeBackend("plain"),
        Tier.TABLES: FakeBackend("tables"),
        Tier.LAYOUT: FakeBackend("layout"),
        Tier.DOCLING: FakeBackend("docling"),
    }
    for tier, backend in backends.items():
        monkeypatch.setitem(BACKENDS, tier, backend)

    def fake_stage1(pdf, numbers, ocr):
        if state["stage1_fails"]:
            raise RuntimeError("signals broke")
        planned = [state["planned"].get(n, Tier.PLAIN) for n in numbers]
        return [(n, t, f"stage1 {t.name} page {n}" if t <= Tier.TABLES else None, 1.0, "") for n, t in zip(numbers, planned)]

    monkeypatch.setattr(router, "_stage1", fake_stage1)
    state["backends"] = backends
    yield state
    for pool in (shared, waiters, docling["pool"]):
        pool.shutdown(wait=False, cancel_futures=True)


def _parts(markdown):
    return markdown.split("\n\n")


def test_pages_stay_in_order_when_tasks_finish_out_of_order(fake, monkeypatch):
    monkeypatch.setattr(router, "CHUNK_PAGES", 1)
    fake["planned"] = {0: Tier.LAYOUT, 2: Tier.LAYOUT, 4: Tier.LAYOUT, 3: Tier.TABLES}
    fake["backends"][Tier.LAYOUT].delay = {0: 0.3, 2: 0.15, 4: 0.0}  # page 4 finishes first

    result = route_pdf(_pdf(6), "https://example.com/a.pdf")

    assert _parts(result.markdown) == [
        "layout page 0",
        "stage1 PLAIN page 1",
        "layout page 2",
        "stage1 TABLES page 3",
        "layout page 4",
        "stage1 PLAIN page 5",
    ]
    assert [o.status for o in result.pages] == ["ok"] * 6


def test_an_error_falls_back_to_the_next_tier(fake):
    fake["planned"] = {1: Tier.DOCLING}
    fake["backends"][Tier.DOCLING].fail = True

    result = route_pdf(_pdf(2), "https://example.com/a.pdf")

    outcome = result.pages[1]
    assert (outcome.tier_planned, outcome.backend_used, outcome.status) == (Tier.DOCLING, "layout", "fallback")
    assert "docling: RuntimeError: boom" in outcome.reason
    assert _parts(result.markdown)[1] == "layout page 1"


def test_a_docling_hang_times_out_resets_the_pool_and_falls_back(fake, monkeypatch):
    monkeypatch.setattr(router, "DOCLING_TIMEOUT_BASE_S", 0.2)
    monkeypatch.setattr(router, "DOCLING_TIMEOUT_PER_PAGE_S", 0.0)
    fake["planned"] = {0: Tier.DOCLING}
    fake["backends"][Tier.DOCLING].delay = {0: 2.0}

    started = time.perf_counter()
    result = route_pdf(_pdf(1), "https://example.com/a.pdf")

    assert time.perf_counter() - started < 1.5
    assert fake["resets"] == 1
    assert result.pages[0].backend_used == "layout"
    assert "Docling took more than 0.2 s" in result.pages[0].reason


def test_an_unavailable_backend_is_skipped(fake):
    fake["planned"] = {0: Tier.DOCLING}
    fake["backends"][Tier.DOCLING]._available = False

    result = route_pdf(_pdf(1), "https://example.com/a.pdf")

    assert fake["backends"][Tier.DOCLING].calls == []
    assert result.pages[0].backend_used == "layout"
    assert "docling: not installed" in result.pages[0].reason


def test_all_docling_pages_go_in_one_call(fake, monkeypatch):
    monkeypatch.setattr(router, "CHUNK_PAGES", 1)  # pages are classified in separate tasks
    fake["planned"] = {1: Tier.DOCLING, 3: Tier.DOCLING, 5: Tier.DOCLING}

    result = route_pdf(_pdf(6), "https://example.com/a.pdf")

    assert fake["backends"][Tier.DOCLING].calls == [[1, 3, 5]]
    assert [o.backend_used for o in result.pages if o.tier_planned is Tier.DOCLING] == ["docling"] * 3


def test_a_page_with_no_text_gets_a_marker(fake):
    fake["planned"] = {1: Tier.LAYOUT}
    fake["backends"][Tier.LAYOUT].empty = {1}
    fake["backends"][Tier.PLAIN].empty = {1}

    result = route_pdf(_pdf(3), "https://example.com/a.pdf")

    assert _parts(result.markdown)[1] == "<!-- page 2: not extracted (plain: empty output) -->"
    assert result.pages[1].status == "failed"
    assert result.pages[1].reason == "layout: empty output; plain: empty output"


def test_a_pdf_where_every_page_failed_returns_empty_markdown(fake, monkeypatch):
    monkeypatch.setattr(
        router, "_stage1", lambda pdf, numbers, ocr: [(n, Tier.PLAIN, None, 1.0, "") for n in numbers]
    )
    fake["backends"][Tier.PLAIN].empty = {0, 1}

    result = route_pdf(_pdf(2), "https://example.com/a.pdf")

    assert result.markdown == ""
    assert [o.status for o in result.pages] == ["failed", "failed"]


def test_a_classification_failure_falls_back_to_plain(fake):
    fake["stage1_fails"] = True

    result = route_pdf(_pdf(2), "https://example.com/a.pdf")

    assert _parts(result.markdown) == ["plain page 0", "plain page 1"]
    assert "classification: RuntimeError: signals broke" in result.pages[0].reason


def test_the_document_budget_is_respected(fake, monkeypatch):
    monkeypatch.setenv("PDF_ROUTER_DOC_TIMEOUT_S", "0.3")
    fake["planned"] = {0: Tier.LAYOUT}
    fake["backends"][Tier.LAYOUT].delay = {0: 2.0}

    started = time.perf_counter()
    result = route_pdf(_pdf(3), "https://example.com/a.pdf")

    assert time.perf_counter() - started < 1.0
    assert _parts(result.markdown)[0] == "<!-- page 1: not extracted (document time budget exceeded) -->"
    assert _parts(result.markdown)[1:] == ["stage1 PLAIN page 1", "stage1 PLAIN page 2"]


def test_a_queued_docling_job_does_not_time_out(fake, monkeypatch):
    # Two PDFs need Docling at once and there's one slot. Each job takes 0.3 s and
    # the timeout is 0.45 s: the second job waits ~0.3 s for the slot, then runs.
    # Counting the wait would time it out.
    monkeypatch.setattr(router, "DOCLING_TIMEOUT_BASE_S", 0.45)
    monkeypatch.setattr(router, "DOCLING_TIMEOUT_PER_PAGE_S", 0.0)
    fake["planned"] = {0: Tier.DOCLING}
    fake["backends"][Tier.DOCLING].delay = {0: 0.3}

    with ThreadPoolExecutor(max_workers=2) as callers:
        results = list(callers.map(lambda _: route_pdf(_pdf(1), "https://example.com/a.pdf"), range(2)))

    assert [r.pages[0].backend_used for r in results] == ["docling", "docling"]
    assert fake["resets"] == 0


def test_real_pools_on_the_mixed_fixture():
    """Real worker processes: stage 1, OCR on the scan (tier 2), tables, merge in order."""
    pytest.importorskip("pymupdf4llm")
    try:
        result = route_pdf((FIXTURES_DIR / "mixed-document.pdf").read_bytes(), "https://example.com/mixed.pdf")
    finally:
        executors.shutdown()

    text = re.sub(r"\s+", " ", result.markdown)
    left = text.index("Left-to-right language model")
    assert left < text.index("Permit me to introduce you to the facility of facsimile transmission.")
    assert text.index("Permit me to introduce") < text.index("SEGMENT-PAIR")
    assert [o.backend_used for o in result.pages] == ["plain", "plain", "pymupdf4llm", "pymupdf_tables", "pymupdf_tables"]
    assert all(o.status == "ok" for o in result.pages)
