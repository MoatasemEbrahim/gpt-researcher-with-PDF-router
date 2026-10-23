"""Probe the PDF fixtures page by page, before building the PageRouter.

For every page it prints the cheap signals a router could classify on, and
how long each candidate backend takes on that page. It also saves what the
current extractor (PyMuPDFScraper) returns, as the "before" half of the
before/after comparison in DECISIONS.md, and the pymupdf4llm Markdown.

Usage (from the repo root):
    python tests/pdf_fixture_probe.py                     # tests/fixtures/pdf/*.pdf
    python tests/pdf_fixture_probe.py path/to/file.pdf    # specific files
    python tests/pdf_fixture_probe.py --docling           # also time Docling (slow)

Not a pytest test (the filename doesn't start with test_), just a dev script.
"""

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

import pymupdf

# Make `gpt_researcher` importable when run as `python tests/pdf_fixture_probe.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pdf"
OUT_DIR = Path(__file__).parent / "fixtures" / "pdf" / "probe-output"
NUMERIC_LINE = re.compile(r"[\s\d.,/%±–\-()]+")


def timed(fn):
    """Run fn() and return (result, elapsed milliseconds)."""
    start = time.perf_counter()
    result = fn()
    return result, round((time.perf_counter() - start) * 1000, 1)


def image_coverage(page):
    """Share of the page area covered by images (0.0 to 1.0)."""
    page_area = page.rect.width * page.rect.height
    covered = 0.0
    for info in page.get_image_info():
        box = pymupdf.Rect(info["bbox"]) & page.rect  # clip to the page
        covered += box.width * box.height
    return round(min(covered / page_area, 1.0), 2)


def column_guess(page):
    """1 or 2: are text blocks split into a left and a right band?"""
    middle = page.rect.width / 2
    left = right = spanning = 0
    for x0, _y0, x1, _y1, text, _no, block_type in page.get_text("blocks"):
        if block_type != 0 or len(text.strip()) < 40:  # skip images and short bits
            continue
        if x1 < middle:
            left += 1
        elif x0 > middle:
            right += 1
        else:
            spanning += 1
    return 2 if left >= 3 and right >= 3 and spanning <= left + right else 1


def ruling_lines(page):
    """Number of straight line segments drawn on the page (table borders, rules)."""
    count = 0
    for path in page.get_drawings():
        for item in path["items"]:
            if item[0] == "l":  # "l" = line; "re" = rectangle
                count += 1
            elif item[0] == "re":
                count += 4
    return count


def font_sizes(page):
    """Distinct font sizes, and largest size divided by the most common one."""
    sizes = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):  # image blocks have no "lines"
            for span in line["spans"]:
                if span["text"].strip():
                    sizes.append(round(span["size"], 1))
    if not sizes:
        return 0, 0.0
    return len(set(sizes)), round(max(sizes) / statistics.mode(sizes), 2)


def text_lines(page):
    """(bbox, text) for every non-empty horizontal text line, in stored order."""
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            if abs(line["dir"][1]) > 0.1:  # rotated, e.g. the arXiv margin stamp
                continue
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                yield pymupdf.Rect(line["bbox"]), text


def back_jump_ratio(page):
    """Share of column lines where stored order jumps from the right column back to the left.

    Works on lines, not blocks: MuPDF merges interleaved rows into full-width
    blocks, which hides the problem. Lines spanning the middle are ignored.
    """
    middle = page.rect.width / 2
    sides = []
    for bbox, _text in text_lines(page):
        if bbox.width < 40:  # skip short bits like page numbers
            continue
        if bbox.x1 < middle:
            sides.append("L")
        elif bbox.x0 > middle:
            sides.append("R")
    jumps = sum(1 for prev, cur in zip(sides, sides[1:]) if prev == "R" and cur == "L")
    return round(jumps / len(sides), 3) if sides else 0.0


def numeric_short_lines(page):
    """Number of short, mostly-numeric lines (a cheap hint that the page has a table)."""
    return sum(1 for _bbox, text in text_lines(page) if len(text) < 14 and NUMERIC_LINE.fullmatch(text))


def garbage_ratio(text):
    """Share of characters that signal a broken text layer."""
    if not text:
        return 0.0
    bad = text.count("�") + text.count("(cid:") * 5
    return round(bad / len(text), 3)


def current_extractor(path):
    """What production returns today for this PDF (content string)."""
    try:
        from gpt_researcher.scraper.pymupdf.pymupdf import PyMuPDFScraper
    except ImportError as error:
        print(f"  (can't import PyMuPDFScraper: {error}; using plain PyMuPDF)")
        with pymupdf.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    content, _images, _title = PyMuPDFScraper(str(path)).scrape()
    return content


def load_pymupdf4llm(warmup_pdf):
    """Import pymupdf4llm in layout mode and pay its cold start once, outside the per-page timings."""
    try:
        import pymupdf4llm
    except ImportError:
        return None
    pymupdf4llm.use_layout(True)
    with pymupdf.open(warmup_pdf) as doc:
        _md, cold_ms = timed(lambda: pymupdf4llm.to_markdown(doc, pages=[0], show_progress=False))
    print(f"pymupdf4llm cold start (page 1 of {warmup_pdf.name}): {cold_ms} ms")
    return pymupdf4llm


def probe_pdf(path, use_docling, pymupdf4llm):
    doc = pymupdf.open(path)
    rows = []
    page_markdown = []
    for page in doc:
        text, plain_ms = timed(page.get_text)
        tables, tables_ms = timed(lambda: page.find_tables().tables)
        distinct_sizes, size_ratio = font_sizes(page)
        row = {
            "page": page.number + 1,
            "chars": len(text),
            "img_cover": image_coverage(page),
            "columns": column_guess(page),
            "lines": ruling_lines(page),
            "fonts": distinct_sizes,
            "max/body": size_ratio,
            "garbage": garbage_ratio(text),
            "back_jump": back_jump_ratio(page),
            "numeric": numeric_short_lines(page),
            "tables": len(tables),
            "plain_ms": plain_ms,
            "tables_ms": tables_ms,
        }
        if pymupdf4llm:
            markdown, row["4llm_ms"] = timed(
                lambda: pymupdf4llm.to_markdown(doc, pages=[page.number], show_progress=False)
            )
            page_markdown.append(markdown)
        rows.append(row)
    doc.close()

    if pymupdf4llm:
        (OUT_DIR / f"{path.stem}.4llm.md").write_text("\n\n".join(page_markdown))

    print_table(rows)

    result = {"file": path.name, "pages": rows}
    if use_docling:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        markdown, result["docling_ms"] = timed(
            lambda: converter.convert(str(path)).document.export_to_markdown()
        )
        (OUT_DIR / f"{path.stem}.docling.md").write_text(markdown)
        print(f"  docling, whole document: {result['docling_ms']} ms")

    (OUT_DIR / f"{path.stem}.baseline.txt").write_text(current_extractor(path))
    return result


def print_table(rows):
    headers = list(rows[0].keys())
    widths = [max(len(h), *(len(str(r.get(h, ""))) for r in rows)) for h in headers]
    print("  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for row in rows:
        print("  " + "  ".join(str(row.get(h, "")).ljust(w) for h, w in zip(headers, widths)))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdfs", nargs="*", type=Path, help="PDF files (default: fixtures dir)")
    parser.add_argument("--docling", action="store_true", help="also time Docling per document")
    args = parser.parse_args()

    pdfs = args.pdfs or sorted(FIXTURES_DIR.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs given and none found in {FIXTURES_DIR}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # PyMuPDF 2.0 imports pymupdf.layout at startup when it's installed, and
    # find_tables() relies on it for borderless tables. _get_layout is private.
    print(f"PyMuPDF layout model active: {pymupdf._get_layout is not None}")
    pymupdf4llm = load_pymupdf4llm(pdfs[0])
    results = []
    for path in pdfs:
        print(f"\n{path.name}")
        results.append(probe_pdf(path, args.docling, pymupdf4llm))

    (OUT_DIR / "signals.json").write_text(json.dumps(results, indent=2))
    print(f"\nSaved baseline text and signals.json to {OUT_DIR}")


if __name__ == "__main__":
    main()
