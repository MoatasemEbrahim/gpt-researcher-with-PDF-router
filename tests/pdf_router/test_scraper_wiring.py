"""PyMuPDFScraper hands the PDF's bytes to the page router and keeps its (content, images, title) contract."""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from gpt_researcher.scraper import pdf_router
from gpt_researcher.scraper.pdf_router import RouterResult, executors
from gpt_researcher.scraper.pymupdf import pymupdf as scraper_module
from gpt_researcher.scraper.pymupdf.pymupdf import PyMuPDFScraper

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"  # tests/fixtures/pdf
PDF_BYTES = b"%PDF-1.7 fake bytes, split across chunks"


class _FakeResponse:
    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield PDF_BYTES[:10]
        yield PDF_BYTES[10:]


def _fake_router(calls):
    def route_pdf(pdf, source_url):
        calls.append((pdf, source_url))
        return RouterResult(markdown="# Routed markdown", title="A title", pages=[])

    return route_pdf


def test_url_bytes_go_to_the_router(monkeypatch):
    calls = []
    monkeypatch.setattr(pdf_router, "route_pdf", _fake_router(calls))

    with patch.object(scraper_module.requests, "get", return_value=_FakeResponse()):
        result = PyMuPDFScraper("https://example.com/paper.pdf").scrape()

    assert result == ("# Routed markdown", [], "A title")
    assert calls == [(PDF_BYTES, "https://example.com/paper.pdf")]


def test_local_file_bytes_go_to_the_router(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pdf_router, "route_pdf", _fake_router(calls))
    path = tmp_path / "paper.pdf"
    path.write_bytes(PDF_BYTES)

    result = PyMuPDFScraper(str(path)).scrape()

    assert result == ("# Routed markdown", [], "A title")
    assert calls == [(PDF_BYTES, str(path))]


def test_ssl_retry_still_works(monkeypatch):
    calls = []
    monkeypatch.setattr(pdf_router, "route_pdf", _fake_router(calls))
    responses = [requests.exceptions.SSLError("bad certificate"), _FakeResponse()]

    def fake_get(url, **kwargs):
        outcome = responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert kwargs.get("verify") is False  # the retry skips verification, as before
        return outcome

    with patch.object(scraper_module.requests, "get", side_effect=fake_get):
        result = PyMuPDFScraper("https://example.com/paper.pdf").scrape()

    assert result[0] == "# Routed markdown"
    assert calls[0][0] == PDF_BYTES


def test_router_disabled_uses_the_legacy_loader(monkeypatch, tmp_path):
    monkeypatch.setenv("PDF_ROUTER_ENABLED", "false")
    calls = []
    monkeypatch.setattr(pdf_router, "route_pdf", _fake_router(calls))
    path = tmp_path / "paper.pdf"
    path.write_bytes(PDF_BYTES)

    with patch.object(scraper_module, "PyMuPDFLoader") as loader:
        loader.return_value.load.return_value = [SimpleNamespace(page_content="legacy text", metadata={"title": "T"})]
        result = PyMuPDFScraper(str(path)).scrape()

    assert calls == []
    assert result == ("legacy text", [], "T")


def test_router_error_gives_the_empty_result(monkeypatch, tmp_path):
    def broken(pdf, source_url):
        raise RuntimeError("cannot open broken document")

    monkeypatch.setattr(pdf_router, "route_pdf", broken)
    path = tmp_path / "paper.pdf"
    path.write_bytes(PDF_BYTES)

    assert PyMuPDFScraper(str(path)).scrape() == ("", [], "")


def test_real_router_on_a_local_fixture():
    try:
        content, images, title = PyMuPDFScraper(str(FIXTURES_DIR / "out-of-order-columns.pdf")).scrape()
    finally:
        executors.shutdown()

    assert "A PDF file describes where each character is drawn on the page." in re.sub(r"\s+", " ", content)
    assert images == []
    assert title == "Notes on Extracting Text from PDF Files"
