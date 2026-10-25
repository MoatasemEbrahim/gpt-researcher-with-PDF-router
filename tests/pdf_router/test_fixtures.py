"""Before/after on the PDF fixtures: the real router must pass every golden snippet.

Each fixture is routed with the real process pools. The test checks the backend
each page used (so a routing change shows up here) and the golden snippets in
tests/pdf_router/golden.py. Scans need an OCR engine or Docling; without either (CI's
plain install) the scan becomes a page marker.
"""

import re
from pathlib import Path

import pytest

from gpt_researcher.scraper.pdf_router import Tier, executors, route_pdf
from gpt_researcher.scraper.pdf_router.backends import BACKENDS, scan_ocr_available
from tests.pdf_router.golden import check, collapse

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"  # tests/fixtures/pdf
SCAN = "scan"  # stands for whichever backend reads scans here
PLAIN, TABLES = "plain", "pymupdf_tables"

# Backend per page. Figures (BERT p3, 5, 13, 15, 16) don't change the tier.
EXPECTED_BACKENDS = {
    "borderless-table": [PLAIN] * 3 + [TABLES] * 6 + [PLAIN] * 3 + [TABLES],
    "mixed-document": [PLAIN, PLAIN, SCAN, TABLES, TABLES],
    "out-of-order-columns": ["pymupdf4llm"],
    "scanned-page": [SCAN],
    "two-column-paper": [PLAIN] * 5 + [TABLES] * 4 + [PLAIN] * 6 + [TABLES],
}


def _scan_backend() -> str:
    if scan_ocr_available():
        return "pymupdf4llm"
    if BACKENDS[Tier.DOCLING].available():
        return "docling"
    return ""


@pytest.mark.parametrize("fixture", sorted(EXPECTED_BACKENDS))
def test_router_passes_the_golden_snippets(fixture):
    scan_backend = _scan_backend()
    if fixture == "scanned-page" and not scan_backend:
        pytest.skip("no OCR engine and no Docling: nothing can read a scan here")
    try:
        result = route_pdf((FIXTURES_DIR / f"{fixture}.pdf").read_bytes(), f"fixtures/{fixture}.pdf")
    finally:
        executors.shutdown()

    expected = [scan_backend if backend == SCAN else backend for backend in EXPECTED_BACKENDS[fixture]]
    assert [outcome.backend_used for outcome in result.pages] == expected
    failed = [description for description, passed in check(fixture, result.markdown, scan_readable=bool(scan_backend)) if not passed]
    assert failed == []
    if not scan_backend and SCAN in EXPECTED_BACKENDS[fixture]:
        # The unreadable scan is marked in place, between its neighbours.
        text = collapse(result.markdown)
        marker = re.search(r"<!-- page 3: not extracted", text)
        assert marker and text.index("Left-to-right language model") < marker.start() < text.index("SEGMENT-PAIR")
