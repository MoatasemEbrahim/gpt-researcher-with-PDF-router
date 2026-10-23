"""Generate tests/fixtures/pdf/out-of-order-columns.pdf.

A two-column page that looks normal, but whose text is *stored* row by row
across both columns (left line 1, right line 1, left line 2, ...), the way
some Word/browser exports write it. Plain text extraction follows the stored
order, so it interleaves the columns mid-sentence. None of the supplied
fixtures do this (they are LaTeX, which stores column by column).

Usage (from the repo root):
    python tests/make_out_of_order_fixture.py
"""

from pathlib import Path

import pymupdf

OUT = Path(__file__).parent / "fixtures" / "pdf" / "out-of-order-columns.pdf"

FONT = "helv"
SIZE = 10
LEADING = 13  # distance between baselines
MARGIN = 54
GUTTER = 24

TITLE = "Notes on Extracting Text from PDF Files"

LEFT = [
    ("heading", "1 Why order matters"),
    ("text", "A PDF file describes where each character is drawn on the page. "
             "It does not record which sentence a character belongs to, or the "
             "order in which a person should read the text. Extraction tools "
             "therefore have to rebuild that order from the positions alone."),
    ("text", "The simplest tools skip that work and return characters in the "
             "order they are stored in the file. When the program that wrote "
             "the file stored them in reading order, the result looks correct."),
    ("heading", "2 When it breaks"),
    ("text", "Some programs write a two-column page one visual row at a time. "
             "The first line of the left column is followed by the first line "
             "of the right column, and so on down the page."),
]

RIGHT = [
    ("text", "Read in stored order, every sentence is cut in half and joined "
             "to an unrelated sentence from the other column. The output still "
             "contains real words and looks like valid prose at a glance."),
    ("text", "That is what makes the problem dangerous for a research agent. "
             "A missing page is easy to notice, but a page of plausible, mixed "
             "sentences is quoted and cited as if it were the source."),
    ("heading", "3 What a fix needs"),
    ("text", "A layout-aware extractor groups characters into blocks, detects "
             "the columns, and reads each column from top to bottom before "
             "moving to the next one. That restores the intended order."),
    ("text", "Detecting the problem is cheaper than fixing it: compare the "
             "stored order of the text blocks with their positions on the "
             "page, and only send the pages that disagree to the costly path."),
]


def wrap(text, width):
    """Split text into lines that fit within width points."""
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if pymupdf.get_text_length(candidate, fontname=FONT, fontsize=SIZE) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def layout(items, width):
    """Turn (kind, text) items into (text, font, size) lines, with blank rows between paragraphs."""
    rows = []
    for kind, text in items:
        if kind == "heading":
            rows.append((text, "hebo", SIZE + 2))  # Helvetica Bold
        else:
            rows.extend((line, FONT, SIZE) for line in wrap(text, width))
        rows.append(None)  # blank row after each item
    return rows


def main():
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4
    column_width = (page.rect.width - 2 * MARGIN - GUTTER) / 2
    right_x = MARGIN + column_width + GUTTER

    page.insert_text((MARGIN, 80), TITLE, fontname="hebo", fontsize=18)

    left_rows = layout(LEFT, column_width)
    right_rows = layout(RIGHT, column_width)

    # The point of the fixture: write row by row across BOTH columns.
    y = 120
    for i in range(max(len(left_rows), len(right_rows))):
        for x, rows in ((MARGIN, left_rows), (right_x, right_rows)):
            if i < len(rows) and rows[i] is not None:
                text, font, size = rows[i]
                page.insert_text((x, y), text, fontname=font, fontsize=size)
        y += LEADING

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.set_metadata({"title": TITLE})
    doc.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
