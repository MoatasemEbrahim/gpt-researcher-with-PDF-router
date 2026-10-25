"""Regression test: PyMuPDFScraper must not leak its downloaded temp file.

When scraping a remote PDF, the scraper downloads it to a
``NamedTemporaryFile(delete=False, suffix=".pdf")`` and then loads it with
``PyMuPDFLoader``. The old code called ``os.remove(temp_filename)`` only on the
success path, so a parse failure (malformed/partial PDF -> ``PyMuPDFLoader.load``
raises) left the temp file behind on disk every time. The exception is then
swallowed by the broad ``except``, so the leak was silent.

That loader path now runs only with ``PDF_ROUTER_ENABLED=false``. By default the
PDF is read into memory and goes through the page router, which writes its own
temp file for its workers and removes it when the call ends; a broken PDF must
still give the empty result and leave nothing behind.
"""

import os
import glob
import tempfile
from unittest.mock import MagicMock, patch

from gpt_researcher.scraper.pymupdf.pymupdf import PyMuPDFScraper


class _FakeResponse:
    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield b"%PDF-1.4 not-a-real-pdf"

    def close(self):
        return None


def _temp_pdfs() -> set:
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "*.pdf")))


def test_broken_pdf_through_the_router_gives_empty_result_and_no_temp_file():
    scraper = PyMuPDFScraper("https://example.com/broken.pdf")

    before = _temp_pdfs()

    with patch(
        "gpt_researcher.scraper.pymupdf.pymupdf.requests.get",
        return_value=_FakeResponse(),
    ):
        content, images, title = scraper.scrape()

    assert (content, images, title) == ("", [], "")
    leaked = _temp_pdfs() - before
    assert not leaked, f"PyMuPDFScraper leaked temp file(s): {leaked}"


def test_tempfile_removed_when_loader_raises(monkeypatch):
    monkeypatch.setenv("PDF_ROUTER_ENABLED", "false")  # the legacy loader path
    scraper = PyMuPDFScraper("https://example.com/broken.pdf")

    before = _temp_pdfs()

    with patch(
        "gpt_researcher.scraper.pymupdf.pymupdf.requests.get",
        return_value=_FakeResponse(),
    ), patch(
        "gpt_researcher.scraper.pymupdf.pymupdf.PyMuPDFLoader"
    ) as mock_loader:
        mock_loader.return_value.load.side_effect = RuntimeError("corrupt PDF")

        content, images, title = scraper.scrape()

    # Broad except still yields the empty-result contract...
    assert (content, images, title) == ("", [], "")
    # ...but no new *.pdf temp file is left behind.
    leaked = _temp_pdfs() - before
    assert not leaked, f"PyMuPDFScraper leaked temp file(s): {leaked}"
