"""Golden snippets for the PDF fixtures: what a person reads on the page (PLAN section 8).

Shared by tests/pdf_router/test_fixtures.py and `tests/pdf_router/tools/probe.py --router`,
so the tests and the before/after comparison judge outputs the same way.
"""

import re

SCAN_SENTENCE = "Permit me to introduce you to the facility of facsimile transmission."
ARXIV_STAMP = "arXiv:1810.04805v2"


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _in_order(text: str, *snippets: str) -> bool:
    positions = [text.find(snippet) for snippet in snippets]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def _table_row(raw: str, *cells: str) -> bool:
    """One Markdown table line holding all the cells."""
    return any("|" in line and all(cell in line for cell in cells) for line in raw.splitlines())


# (description, needs the scan to be readable, check(collapsed text, raw text))
CHECKS = {
    "scanned-page": [
        ("scan sentence", True, lambda text, raw: SCAN_SENTENCE in text),
        ("signature P.J. CROSS", True, lambda text, raw: "P.J. CROSS" in text),
    ],
    "mixed-document": [
        ("scan sentence", True, lambda text, raw: SCAN_SENTENCE in text),
        (
            "order: BERT text, then the scan, then the RoBERTa table",
            True,
            lambda text, raw: _in_order(text, "Left-to-right language model", "Permit me to introduce", "SEGMENT-PAIR"),
        ),
    ],
    "out-of-order-columns": [
        (
            "a sentence that crosses a line comes out in one run",
            False,
            lambda text, raw: "A PDF file describes where each character is drawn on the page." in text,
        ),
    ],
    "borderless-table": [
        (
            "SEGMENT-PAIR row as one Markdown table row",
            False,
            lambda text, raw: _table_row(raw, "SEGMENT-PAIR", "90.4/78.7", "84.0", "92.9"),
        ),
    ],
    "two-column-paper": [
        (
            "sentence across the margin stamp is joined",
            False,
            lambda text, raw: "predict the original vocabulary id of the masked word based only on its context" in text,
        ),
    ],
}

COMMON = [
    ("not empty", False, lambda text, raw: bool(text.strip())),
    ("no arXiv stamp in the body text", False, lambda text, raw: ARXIV_STAMP not in text),
]


def check(fixture: str, text: str, *, scan_readable: bool = True) -> list[tuple[str, bool]]:
    """(description, passed) for each golden check of a fixture (by file stem).

    scan_readable=False leaves out the checks that need OCR, for installs without it.
    """
    collapsed = collapse(text)
    return [
        (description, check_fn(collapsed, text))
        for description, needs_ocr, check_fn in COMMON + CHECKS.get(fixture, [])
        if scan_readable or not needs_ocr
    ]
