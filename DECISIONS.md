# PDF page router: decisions

What was built, what was measured, and what was rejected. Design diagrams, per-fixture flows and the full numbers are in [`gpt_researcher/scraper/pdf_router/README.md`](gpt_researcher/scraper/pdf_router/README.md). All timings are from one Apple-silicon Mac unless marked Linux.

## The problem, as found in the code

- `PyMuPDFScraper.scrape()` ran one extractor over the whole file. Both ways in (`get_scraper()` for `.pdf` URLs, `Scraper._retry_as_pdf()` for HTML scrapers that got PDF bytes) go through it, so it is the one change point. Every exception became `("", [], "")`, which the `Scraper` then drops as "too short": a scanned PDF vanished from the research silently.
- Measured on the fixtures, today's extractor fails 10 of 17 golden checks: an empty file for the scan, the scanned page missing from the mixed document, tables flattened one cell per line, figure labels dumped as text, the arXiv margin stamp landing mid-sentence, no headings.
- **Fixture corrections:** the two arXiv papers do *not* interleave columns (LaTeX stores text column by column), and RoBERTa is two-column, not single-column. None of the supplied fixtures stores text out of reading order, so a fifth fixture was generated (`tests/fixtures/pdf/out-of-order-columns.pdf`; its generator is in commit `0ad912ed`) whose text is stored row by row across both columns, the way some Word and browser exports do it.

## Classification: cheap signals, evaluated in order

- Per page: `chars`, `img_cover` (image area ÷ page area), `garbage` (`�` and `(cid:` density), `back_jump_ratio` (how often stored line order jumps from the right column back to the left), and `tables` / `pictures` from PyMuPDF's layout model. One text extraction plus one model call; ~150 ms a page, the model skipped on scans.
- Rules, first match wins: scan (`chars < 50`, `img_cover ≥ 0.5`) → tier 2 if an OCR engine is installed, else tier 3; `garbage ≥ 0.05` → tier 3; `back_jump_ratio ≥ 0.15` → tier 2; `tables ≥ 1` → tier 1; otherwise tier 0. Figures never change a tier: every tier replaces the text inside a figure with `<!-- figure -->` and keeps the caption.
- Predict only, no verify-and-escalate: no fixture showed a wrong prediction, and re-parsing on a quality check makes cost unpredictable inside a research loop. Failures still fall back (below).
- **Rejected:** column count (2 on nearly every LaTeX page, so it would send everything to the expensive tier); ruling lines (they mark figures, not tables; borderless tables have none); a numeric-short-lines count (missed tables made of words, false positives on figure pages; replaced by the layout model's `table` boxes); `find_tables()` inside the classifier (as expensive as parsing); `get_text(sort=True)` as a fix for reading order (sorting by position still mixes columns line by line); block-level reading-order checks (MuPDF merges interleaved rows into full-width blocks, which hides the problem; the check must use lines).

## The ladder: four tiers, each closing a gap the one below cannot

| Tier | Backend | Closes | Cost / page |
| --- | --- | --- | --- |
| 0 | PyMuPDF text (ligatures expanded, hyphens joined, rotated margin stamps and figure text dropped) | baseline, already cleaner than today | ~8 ms |
| 1 | tier 0 + `find_tables()` → Markdown tables in place | tables, including borderless ones | ~350 ms on table pages (mostly `to_markdown()`) |
| 2 | pymupdf4llm in layout mode | text stored out of order, headings, OCR for scans | ~210 ms warm; a scan ~1.6 s |
| 3 | Docling, one call per document over a sub-PDF of its routed pages | scans when tier 2 has no OCR engine, broken text layers, final fallback | ~780 ms warm, ~8 s first call per process, a scan ~5 s |

- Tiers 0 and 1 share one renderer and need only `pymupdf`. Tier 1 keeps its place over tier 2 because its tables are cleaner (pymupdf4llm merged a section row into the `SEGMENT-PAIR` row) and it works without the optional packages.
- Scans go to tier 2 when RapidOCR or Tesseract data is present: its output matched or beat Docling's on the fixture (date and "Our Ref." kept in place) at a third of the time. pymupdf4llm picks its OCR engine silently and returns nothing for scans without one, so the router checks for an engine itself.
- **Result on the fixtures:** router 17/17 golden checks, Docling 17/17, today's extractor 7/17, with the router 4–10× faster than Docling per document (1.8 s for BERT's 16 pages). The one visible gap against Docling is `##` headings on tier-0 pages.

## Parallelism and its constraints

- Workers are processes, not threads: PyMuPDF isn't thread-safe and the work is CPU-bound. One shared `ProcessPoolExecutor` per process, because the scraper already runs many URLs at once in threads; a pool per PDF would multiply processes. `spawn` on every platform: fork is unsafe once the scraper's threads exist.
- Stage 1 runs in the pool in chunks of 2 pages: signals, classify, and tiers 0–1 rendered right there, reusing the page's layout result (`find_tables()` would otherwise run the model a second time: 240 → 30–90 ms). Stage 2 sends tier-2 chunks to the same pool and all tier-3 pages to a dedicated Docling pool in one call, after every page is classified.
- A process-wide Docling slot (`PDF_ROUTER_DOCLING_CONCURRENCY`, default 1) caps running Docling jobs across all PDFs. A job's timeout starts when it holds a slot, not while it queues behind another PDF's job; otherwise a healthy job could time out and its reset would kill the other job.
- Measured: a 16-page paper in 1.8 s warm; six arXiv URLs at once through the real `Scraper` in 18 s with a 3.4 GB peak (Linux: 54 s, 2.8 GB, identical output). Memory per shared worker: ~260 MB at start, ~650 MB after parsing, ~1.2 GB once it has run OCR; the Docling worker ~1.3 GB. Each spawned worker re-imports the package (~1.2 s), paid once per worker.

## Failure handling

- Fallback only ever moves down the ladder: Docling → pymupdf4llm (if installed) → plain; pymupdf4llm → plain; tables → plain. A tier that raises, times out, returns no text or isn't installed hands the page down; each attempt is recorded in `PageOutcome.reason`. If stage 1 itself fails, its pages go to tier 0.
- Docling gets its own timeout (30 s + 10 s × pages); on timeout its pool is stopped and rebuilt, because a running task can't be cancelled through its future. The shared pool has no per-chunk timeout (its tasks can't be killed either, and a timeout would fire on queued tasks); everything is bounded by a per-document budget (`PDF_ROUTER_DOC_TIMEOUT_S`, default 120 s). When it runs out, finished pages are returned and the rest are marked.
- A page with no text becomes `<!-- page N: not extracted (reason) -->`, visible and short. If every page failed the content is `""`, so a dead PDF does not slip past the scraper's length check. One summary line is logged per document.
- `PDF_ROUTER_ENABLED=false` keeps the old `PyMuPDFLoader` path as an escape hatch. The router is imported on first use, so importing the scraper stays as cheap as before (it had jumped from 0.6 s / 105 MB to 1.0 s / 258 MB when imported at module level).

## Trade-offs made

- Latency vs quality: the router is slower than today's extractor (1.8 s vs 0.04 s for BERT) because the layout model costs ~140 ms a page. It buys tables, figure handling and scans, and it is still 4–10× cheaper than Docling everywhere.
- Scope: the browser scraper's PDF path and the local/online document loaders still use their old extractors. `arxiv.org/pdf/<id>` *without* `.pdf` goes to `ArxivScraper` (abstract only) and never reaches the router; two of the four fixtures are arXiv papers, so this is worth a product decision.
- Dependencies: `pymupdf` 2.0 itself requires `pymupdf4llm` and the layout model, so tiers 0–2 work from a plain install. Only OCR (`rapidocr`, or system Tesseract) and Docling (pulls in PyTorch) are optional, in the `pdf-router` extra; without them scans become page markers. Docling checks the Hugging Face Hub every time a converter starts, so offline deployments need `HF_HUB_OFFLINE=1`.
- Figures: a vision-model description per figure (Docling with SmolVLM or Granite Vision) was designed, then dropped before the ~0.5–6 GB model download; the placeholder is also the fallback whenever a higher tier fails.

## Verification

- 57 tests across signals, classification, each backend, the router (fake backends and thread pools for order, fallback, timeouts, the budget, one Docling call per document, the Docling slot), the scraper wiring, and the five fixtures with the real pools. The repo's CI command passes in Linux on Python 3.12 and 3.14 (625 passed, 0 failed; the base commit passes 572). Tests that need OCR or Docling skip or expect markers when those aren't installed.
- End to end with the real `Scraper` on public URLs: arXiv PDFs routed with no fallbacks; a 75-page paper in 15 s; a 404 dropped as before; scanned National Archives PDFs (no text layer, empty today) OCR'd at ~1.8 s a page, with two unreadable grey cover sheets correctly marked.
- One paid `GPTResearcher` run on BERT and RoBERTa with the router on and off ($0.11 vs $0.14): both reports quote the right table numbers. On LaTeX papers the flattened cells stay in reading order and the language model rebuilds the tables itself, so the router made no visible difference there. Its gains are on scans, out-of-order text and figure noise, which that run didn't exercise; no paid run was made on a scan.

## Library survey

- **Used:** PyMuPDF (signals, tiers 0–1; AGPL-3.0 or commercial, already a dependency), pymupdf4llm with pymupdf-layout (tier 2; the only cheap option that fixed out-of-order columns; the installed wheels carry no licence metadata, so confirm with Artifex before shipping), Docling (tier 3; code MIT, layout weights Apache-2.0, table weights CDLA-Permissive-2.0), RapidOCR (Apache-2.0).
- **Measured and not used:** nothing else was run on the fixtures. The rest were excluded on documentation: pypdfium2 (same raw speed, no tables or layout; the swap-in if AGPL is a blocker), pdfminer.six and pypdf (pure Python, text only), pdfplumber / Camelot / tabula (table-only; `find_tables` covers ours), Poppler `pdftotext` (system binary, doesn't fix reading order), markitdown (pdfminer underneath), Unstructured / marker / MinerU (overlap Docling, heavier or harder licences), GROBID (a Java service for papers only), vision models and cloud APIs (per-page cost; the only way to read charts). Raw extraction is ~8 ms a page and is not where the time goes; the expensive tiers buy reading order, tables and OCR.

## Known weak spots

- Thresholds come from five fixtures, four of them from two LaTeX papers; the broken-text-layer rule has no fixture at all; the out-of-order fixture is synthetic; word-only tables are untested.
- `back_jump_ratio` fires on grids, not only on broken order: GPT-3 sent 14 of 75 pages to tier 2 (tables, an author grid, example boxes, references). The cost is fine; whether tier 2's tables match tier 1's on those pages is unverified.
- `find_tables` merges cells on RoBERTa's largest results table; rows survive, some columns are combined.
- Timed-out work in the shared pool keeps running; stopping a Docling job uses the pool's private `_processes`, and with more than one Docling worker a reset kills the other PDFs' jobs too.
- The whole PDF is held in memory and copied to the workers per chunk; no size limit, as before. Four workers can reach ~3.7 GB.
- The 120 s budget covers ~65 scanned pages at ~1.8 s each. Linux in Docker ran 2–3× slower than the Mac, uninvestigated.

## Another week

- Verify-and-escalate with a per-document cost budget; headings in tier 0 from font size and weight; vision-model descriptions of figures and charts; math to LaTeX.
- Send workers a temp-file path instead of the bytes; a faster table-to-Markdown path (`table.extract()` is 8 ms but drops decimal points); cache parsed PDFs by content hash.
- Route the browser scraper and the document loaders through the router; try pdf_oxide or LiteParse as a licence-friendly engine for tiers 0–2.
