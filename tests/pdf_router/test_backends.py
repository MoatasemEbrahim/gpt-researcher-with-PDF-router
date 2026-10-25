"""Page backends for the PDF page router.

Tiers 0-1 run on generated pages and the committed fixtures. Tiers 2-3 are
smoke tests, skipped when pymupdf4llm / Docling aren't installed; the Docling
one takes ~20-30 s (model start-up).
"""

import re
from pathlib import Path

import pymupdf
import pytest

from gpt_researcher.scraper.pdf_router.backends import BACKENDS, FIGURE_MARKER
from gpt_researcher.scraper.pdf_router.backends.pymupdf_text import render_page
from gpt_researcher.scraper.pdf_router.types import Tier

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"  # tests/fixtures/pdf
SCAN_SENTENCE = "Permit me to introduce you to the facility of facsimile transmission."


def _fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# --- tiers 0 and 1 ---


def test_hyphen_at_line_end_is_joined_only_before_lowercase():
    doc = pymupdf.open()
    page = doc.new_page()
    for row, text in enumerate(["We introduce a new language repre-", "sentation model called BERT."]):
        page.insert_text((72, 100 + row * 12), text, fontname="helv", fontsize=10)
    for row, text in enumerate(["Part One of Section-", "Two describes it."]):
        page.insert_text((72, 300 + row * 12), text, fontname="helv", fontsize=10)

    markdown = BACKENDS[Tier.PLAIN].parse(doc.tobytes(), [0])[0]

    assert "language representation model" in markdown
    assert "Section- Two" in markdown


def test_plain_drops_margin_stamp_and_expands_ligatures():
    markdown = BACKENDS[Tier.PLAIN].parse(_fixture("two-column-paper.pdf"), [0])[0]

    assert "arXiv:1810.04805v2" not in markdown
    assert "ﬁ" not in markdown
    assert "fine-tuning" in markdown


def test_sideways_page_keeps_its_text_and_drops_the_page_number():
    """A landscape table set sideways in a portrait page: the text is rotated 90 degrees, the page number is not.

    The old rule dropped every rotated line, so such a page came back empty and got a marker.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for row in range(12):
        point = pymupdf.Point(100 + row * 14, 780)
        page.insert_text(point, f"Row {row}: model A 91.{row} model B 88.{row}", fontsize=9, morph=(point, pymupdf.Matrix(90)))
    page.insert_text((270, 820), "Page 42 of 60", fontsize=9)  # horizontal page furniture

    markdown = BACKENDS[Tier.PLAIN].parse(doc.tobytes(), [0])[0]

    assert "Row 0: model A 91.0 model B 88.0" in markdown
    assert "Row 11:" in markdown
    assert "Page 42" not in markdown


def test_figure_text_becomes_a_marker_and_caption_stays():
    markdown = BACKENDS[Tier.PLAIN].parse(_fixture("two-column-paper.pdf"), [2])[2]

    assert markdown.count(FIGURE_MARKER) == 1
    assert "E[CLS]" not in markdown
    assert "Figure 1: Overall pre-training and fine-tuning procedures for BERT." in markdown


def test_tables_tier_writes_markdown_table_in_place():
    markdown = BACKENDS[Tier.TABLES].parse(_fixture("borderless-table.pdf"), [4])[4]

    assert "|SEGMENT-PAIR|90.4/78.7|84.0|92.9|64.2|" in markdown
    assert markdown.count("88.7/76.2") == 1  # a table value, not repeated as a loose line
    # The page opens with the table, then its caption, then the body text.
    assert markdown.startswith("|Model|")
    caption = markdown.index("Table 2: Development set results")
    assert markdown.index("|SEGMENT-PAIR|") < caption < markdown.index("SENTENCE-PAIR+NSP: Each input contains")


def test_plain_tier_has_no_markdown_table():
    markdown = BACKENDS[Tier.PLAIN].parse(_fixture("borderless-table.pdf"), [4])[4]

    assert "|SEGMENT-PAIR|" not in markdown
    assert "SEGMENT-PAIR" in markdown


def test_tables_tier_reuses_the_layout_result(monkeypatch):
    doc = pymupdf.open(stream=_fixture("borderless-table.pdf"))
    page = doc[4]
    page.get_layout()  # as classification does
    calls = []
    model = pymupdf._get_layout
    monkeypatch.setattr(pymupdf, "_get_layout", lambda *args, **kwargs: (calls.append(1), model(*args, **kwargs))[1])

    markdown = render_page(page, tables=True)

    assert calls == []  # find_tables() didn't run the model again
    assert "|SEGMENT-PAIR|90.4/78.7|84.0|92.9|64.2|" in markdown
    assert pymupdf._get_layout is not model  # our counter is back in place after the call


# --- tier 2: pymupdf4llm ---


def test_llm_markdown_fixes_reading_order_and_figures(capsys):
    pytest.importorskip("pymupdf4llm")
    backend = BACKENDS[Tier.LAYOUT]

    columns = backend.parse(_fixture("out-of-order-columns.pdf"), [0])[0]
    figure = backend.parse(_fixture("two-column-paper.pdf"), [2])[2]

    assert "A PDF file describes where each character is drawn on the page." in _collapse(columns)
    assert FIGURE_MARKER in figure
    assert "data:image" not in figure and "E[CLS]" not in figure
    assert "Figure 1: Overall pre-training" in figure
    assert capsys.readouterr().out == ""  # parser messages kept out of stdout


def test_llm_markdown_ocrs_a_scan():
    pytest.importorskip("pymupdf4llm")
    from gpt_researcher.scraper.pdf_router.backends import scan_ocr_available

    if not scan_ocr_available():
        pytest.skip("no OCR engine for pymupdf4llm")

    markdown = BACKENDS[Tier.LAYOUT].parse(_fixture("scanned-page.pdf"), [0])[0]

    assert SCAN_SENTENCE in _collapse(markdown)
    assert "P.J. CROSS" in markdown


# --- tier 3: Docling ---


def test_docling_parses_non_contiguous_pages_in_one_call():
    pytest.importorskip("docling")

    # mixed-document: BERT p1-2, the scan, RoBERTa p5-6. Pages 2 and 4 = the scan + RoBERTa p6.
    result = BACKENDS[Tier.DOCLING].parse(_fixture("mixed-document.pdf"), [2, 4])

    assert set(result) == {2, 4}
    assert SCAN_SENTENCE in _collapse(result[2])
    assert "Table 3: Perplexity" not in result[2] and "Table 3: Perplexity" in result[4]
    assert "<!-- image -->" not in result[2] + result[4]  # our marker, not Docling's


def test_plain_tier_works_on_older_pymupdf_without_get_layout(monkeypatch):
    monkeypatch.delattr(pymupdf.Page, "get_layout")  # PyMuPDF 1.26.0 has no get_layout at all

    markdown = BACKENDS[Tier.PLAIN].parse(_fixture("two-column-paper.pdf"), [0])[0]

    assert "We introduce a new language representation model called BERT" in markdown
