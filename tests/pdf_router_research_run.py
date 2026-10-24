"""One real research run on two PDFs, with and without the PDF page router.

GPTResearcher researches exactly BERT's and RoBERTa's PDFs (no search engine),
once with the router and once with PDF_ROUTER_ENABLED=false, and saves both
reports. It then checks the numbers each report cites against the papers:

- in a table: the number appears in a Markdown table row of the routed text,
  so the report could only have read it correctly from a table that kept its rows;
- in the text: it appears somewhere in the papers' text (either extractor);
- not found: it appears nowhere in the papers (a calculation, or an error).

Not a pytest test: it calls OpenAI and costs money. Needs OPENAI_API_KEY in
gpt-researcher/.env (gitignored), loaded the same way main.py does.

Usage (from the repo root):
    python tests/pdf_router_research_run.py           # two research runs (costs money)
    python tests/pdf_router_research_run.py --reuse   # re-check the saved reports only (free)
"""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Make `gpt_researcher` importable when run as `python tests/pdf_router_research_run.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT_DIR = Path(__file__).parent / "fixtures" / "pdf" / "probe-output"
QUERY = "How does RoBERTa change BERT's pre-training, and how much do those changes matter on SQuAD and MNLI?"
SOURCES = ["https://arxiv.org/pdf/1810.04805.pdf", "https://arxiv.org/pdf/1907.11692.pdf"]
NUMBER = re.compile(r"\d+\.\d+(?:/\d+\.\d+)?")  # 84.0, 90.4/78.7: decimals, as in the result tables


def _numbers(text: str) -> set[str]:
    """Decimal numbers in text; a pair like 88.7/76.2 also counts as 88.7 and 76.2."""
    found = set()
    for match in NUMBER.findall(text):
        found.add(match)
        found.update(match.split("/"))
    return found


async def research(router_enabled: bool) -> tuple[str, float, list[str]]:
    from gpt_researcher import GPTResearcher

    os.environ["PDF_ROUTER_ENABLED"] = "true" if router_enabled else "false"
    researcher = GPTResearcher(query=QUERY, source_urls=SOURCES, complement_source_urls=False)
    await researcher.conduct_research()
    report = await researcher.write_report()
    return report, researcher.get_costs(), researcher.get_source_urls()


def source_texts() -> tuple[set[str], set[str]]:
    """Numbers in the papers' table rows (routed text), and numbers anywhere in their text."""
    from gpt_researcher.scraper.pdf_router import executors
    from gpt_researcher.scraper.pymupdf.pymupdf import PyMuPDFScraper

    table_numbers, all_numbers = set(), set()
    try:
        for url in SOURCES:
            for enabled in ("true", "false"):
                os.environ["PDF_ROUTER_ENABLED"] = enabled
                content, _images, _title = PyMuPDFScraper(url).scrape()
                all_numbers.update(_numbers(content))
                if enabled == "true":
                    for line in content.splitlines():
                        if line.startswith("|"):
                            table_numbers.update(_numbers(line))
    finally:
        executors.shutdown()
    return table_numbers, all_numbers


def classify_numbers(report: str, table_numbers: set[str], all_numbers: set[str]) -> dict[str, list[str]]:
    cited = sorted(set(NUMBER.findall(report)), key=lambda n: (len(n), n))
    in_tables = lambda n: n in table_numbers or all(part in table_numbers for part in n.split("/"))  # noqa: E731
    in_text = lambda n: n in all_numbers or all(part in all_numbers for part in n.split("/"))  # noqa: E731
    return {
        "in a table": [n for n in cited if in_tables(n)],
        "in the text only": [n for n in cited if in_text(n) and not in_tables(n)],
        "not found in the papers": [n for n in cited if not in_text(n)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reuse", action="store_true", help="re-check the saved reports; no new research runs")
    args = parser.parse_args()

    runs_file = OUT_DIR / "research-runs.json"
    runs = {}
    if args.reuse:
        saved = json.loads(runs_file.read_text())
        for label in ("after", "before"):
            runs[label] = ((OUT_DIR / f"research-{label}.md").read_text(), saved[label]["cost"], saved[label]["sources"])
    else:
        load_dotenv()
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("OPENAI_API_KEY is not set: add it to gpt-researcher/.env")
        for label, enabled in (("after", True), ("before", False)):
            print(f"Researching with the router {'on' if enabled else 'off'} ...")
            report, cost, sources = asyncio.run(research(enabled))
            (OUT_DIR / f"research-{label}.md").write_text(report)
            runs[label] = (report, cost, sources)
            print(f"  {len(report)} chars, cost ${cost:.4f}, sources {sources}")
        runs_file.write_text(json.dumps({label: {"cost": run[1], "sources": run[2]} for label, run in runs.items()}, indent=2))

    table_numbers, all_numbers = source_texts()
    lines = [
        "# Research run, before and after the router",
        "",
        f"Query: *{QUERY}*",
        "",
        f"Sources (only these, no web search): {', '.join(SOURCES)}",
        "",
        "Generated by `python tests/pdf_router_research_run.py`. Reports: `research-before.md`, `research-after.md`.",
        "Numbers are decimals cited in each report, checked against the papers' text.",
        "",
        "| | Before (router off) | After (router on) |",
        "| --- | --- | --- |",
        f"| Report length | {len(runs['before'][0])} chars | {len(runs['after'][0])} chars |",
        f"| Cost (repo's estimate) | ${runs['before'][1]:.4f} | ${runs['after'][1]:.4f} |",
    ]
    verdicts = {label: classify_numbers(runs[label][0], table_numbers, all_numbers) for label in runs}
    for kind in ("in a table", "in the text only", "not found in the papers"):
        before, after = verdicts["before"][kind], verdicts["after"][kind]
        lines.append(f"| Numbers {kind} | {len(before)}: {', '.join(before) or '-'} | {len(after)}: {', '.join(after) or '-'} |")
    text = "\n".join(lines) + "\n"
    (OUT_DIR / "research-comparison.md").write_text(text)
    print("\n" + text)


if __name__ == "__main__":
    main()
