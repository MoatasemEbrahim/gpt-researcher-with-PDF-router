"""Signals and classification for the PDF page router.

Most tests build a tiny PDF in memory (with PyMuPDF, the way the
out-of-order fixture was made). Table and figure detection comes from
PyMuPDF's layout model, which needs real pages, so those tests use the
committed fixtures.
"""

from pathlib import Path
from unittest.mock import patch

import pymupdf
import pytest

from gpt_researcher.scraper.pdf_router import PageSignals, Tier, classify, compute_signals

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"  # tests/fixtures/pdf
WIDTH, HEIGHT = 595, 842  # A4
LEFT_X, RIGHT_X = 54, 320
TOP, LEADING = 100, 13
ROWS = 20

WITH_OCR = dict(scan_ocr_available=True)


def _column_line(column: str, row: int) -> str:
    return f"{column} column, line {row}, with enough words"


def _new_doc():
    doc = pymupdf.open()
    doc.new_page(width=WIDTH, height=HEIGHT)
    return doc


def _two_columns(doc, stored_in_reading_order: bool):
    """Write two columns of text, either column by column or row by row across both."""
    page = doc[0]
    left = [(LEFT_X, TOP + row * LEADING, _column_line("Left", row)) for row in range(ROWS)]
    right = [(RIGHT_X, TOP + row * LEADING, _column_line("Right", row)) for row in range(ROWS)]
    if stored_in_reading_order:
        order = left + right
    else:
        order = [line for pair in zip(left, right) for line in pair]
    for x, y, text in order:
        page.insert_text((x, y), text, fontname="helv", fontsize=10)


def _scan_doc():
    doc = _new_doc()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
    pixmap.clear_with(200)
    doc[0].insert_image(doc[0].rect, pixmap=pixmap, keep_proportion=False)  # fill the page, like a scan
    return doc


def _signals(**overrides) -> PageSignals:
    """A normal text page, with selected fields replaced."""
    values = dict(chars=3000, img_cover=0.0, garbage=0.0, back_jump_ratio=0.0, tables=0, pictures=0)
    values.update(overrides)
    return PageSignals(**values)


# --- signals on generated pages, then the tier ---


def test_two_columns_in_reading_order_is_plain():
    doc = _new_doc()
    _two_columns(doc, stored_in_reading_order=True)

    signals = compute_signals(doc[0])

    assert signals.chars > 500
    assert signals.back_jump_ratio == 0.0
    assert (signals.tables, signals.pictures) == (0, 0)
    assert classify(signals, **WITH_OCR) == Tier.PLAIN


def test_two_columns_stored_row_by_row_goes_to_layout():
    doc = _new_doc()
    _two_columns(doc, stored_in_reading_order=False)

    signals = compute_signals(doc[0])

    # 40 column lines alternate L, R, L, R ...: 19 jumps back from right to left.
    assert signals.back_jump_ratio == pytest.approx(19 / 40)
    assert classify(signals, **WITH_OCR) == Tier.LAYOUT


def test_scanned_page_goes_to_ocr_tier_without_running_the_layout_model():
    doc = _scan_doc()

    with patch.object(pymupdf.Page, "get_layout") as get_layout:
        signals = compute_signals(doc[0])

    get_layout.assert_not_called()
    assert signals.chars == 0
    assert signals.img_cover == pytest.approx(1.0)
    assert classify(signals, **WITH_OCR) == Tier.LAYOUT
    assert classify(signals, scan_ocr_available=False) == Tier.DOCLING


def test_broken_text_layer_goes_to_docling():
    doc = _new_doc()
    for row in range(10):
        doc[0].insert_text((LEFT_X, TOP + row * LEADING), "(cid:12)(cid:34)(cid:56) (cid:78)", fontname="helv")

    signals = compute_signals(doc[0])

    assert signals.garbage >= 0.05
    assert classify(signals, **WITH_OCR) == Tier.DOCLING


def test_diagonal_watermark_is_ignored_by_reading_order_signal():
    doc = _new_doc()
    # A 45-degree watermark in the right half, stored before the columns. Its box is
    # wide, so only the rotation check keeps it from counting as a right-column line
    # (which would add a right-to-left jump into the left column).
    point = pymupdf.Point(330, 600)
    doc[0].insert_text(point, "CONFIDENTIAL DRAFT", fontname="helv", fontsize=30, morph=(point, pymupdf.Matrix(-45)))
    _two_columns(doc, stored_in_reading_order=True)

    signals = compute_signals(doc[0])

    assert "CONFIDENTIAL" in doc[0].get_text()  # still counted as text
    assert signals.back_jump_ratio == 0.0


def test_missing_layout_model_means_no_tables_or_figures(monkeypatch):
    monkeypatch.setattr(pymupdf, "_get_layout", None)  # as if pymupdf-layout were not installed
    doc = pymupdf.open(FIXTURES_DIR / "borderless-table.pdf")

    signals = compute_signals(doc[4])

    assert (signals.tables, signals.pictures) == (0, 0)
    assert classify(signals, **WITH_OCR) == Tier.PLAIN


# --- table and figure detection on the fixtures (layout model) ---


@pytest.mark.parametrize(
    "fixture, table_pages, picture_pages",
    [
        # RoBERTa: borderless tables; no figures
        ("borderless-table.pdf", {4, 5, 6, 7, 8, 9, 13}, set()),
        # BERT: Figures 1-5 on p3, 5, 13, 15, 16; tables on p6-9 and 16
        ("two-column-paper.pdf", {6, 7, 8, 9, 16}, {3, 5, 13, 15, 16}),
    ],
)
def test_layout_model_finds_tables_and_figures(fixture, table_pages, picture_pages):
    doc = pymupdf.open(FIXTURES_DIR / fixture)

    signals = [compute_signals(page) for page in doc]

    assert {n + 1 for n, s in enumerate(signals) if s.tables} == table_pages
    assert {n + 1 for n, s in enumerate(signals) if s.pictures} == picture_pages


# --- rule order and thresholds, on hand-written signals ---


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({}, Tier.PLAIN),
        # scan rule: both conditions needed
        ({"chars": 49, "img_cover": 0.5}, Tier.LAYOUT),
        ({"chars": 50, "img_cover": 1.0}, Tier.PLAIN),
        ({"chars": 0, "img_cover": 0.49}, Tier.PLAIN),
        # thresholds are inclusive
        ({"garbage": 0.05}, Tier.DOCLING),
        ({"garbage": 0.049}, Tier.PLAIN),
        ({"back_jump_ratio": 0.15}, Tier.LAYOUT),
        ({"back_jump_ratio": 0.149}, Tier.PLAIN),
        ({"tables": 1}, Tier.TABLES),
        # a figure doesn't change the tier (every tier writes a figure marker)
        ({"pictures": 2}, Tier.PLAIN),
        ({"pictures": 1, "tables": 1}, Tier.TABLES),
        ({"pictures": 1, "back_jump_ratio": 0.3}, Tier.LAYOUT),
        # earlier rules win
        ({"chars": 0, "img_cover": 1.0, "tables": 3}, Tier.LAYOUT),
        ({"garbage": 0.2, "back_jump_ratio": 0.5}, Tier.DOCLING),
        ({"back_jump_ratio": 0.3, "tables": 1}, Tier.LAYOUT),
    ],
)
def test_rules(overrides, expected):
    assert classify(_signals(**overrides), **WITH_OCR) == expected


def test_ocr_flag_only_affects_scans():
    for overrides in ({}, {"back_jump_ratio": 0.3}, {"tables": 1}, {"garbage": 0.1}, {"pictures": 1}):
        signals = _signals(**overrides)
        assert classify(signals, scan_ocr_available=False) == classify(signals, scan_ocr_available=True)
