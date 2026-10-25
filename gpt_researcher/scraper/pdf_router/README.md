# PDF page router

The router classifies each page of a PDF and parses it with the cheapest backend that can handle it. The pages are merged back into one Markdown string, which `PyMuPDFScraper` returns through the existing `(content, image_urls, title)` contract.

The decisions, trade-offs and weak spots are summarised in [`DECISIONS.md`](../../../DECISIONS.md) at the repo root; this file holds the diagrams and the numbers.

Status: built and wired into `PyMuPDFScraper` (Phases 2–5). Both ways into it go through the router: `get_scraper()` for `.pdf` URLs, and `Scraper._retry_as_pdf()` when an HTML scraper got PDF bytes.

## Structure

```mermaid
flowchart LR
    subgraph pkg["gpt_researcher/scraper/pdf_router/"]
        init["__init__.py<br/>exports"]
        types["types.py<br/>Tier, PageSignals,<br/>PageOutcome, RouterResult"]
        settings["settings.py<br/>PDF_ROUTER_* variables"]
        signals["signals.py<br/>compute_signals()"]
        classify["classify.py<br/>is_scan(), classify()"]
        router["router.py<br/>route_pdf(), FALLBACK"]
        executors["executors.py<br/>shared pool, Docling pool,<br/>Docling slot"]
        subgraph backends["backends/"]
            binit["__init__.py<br/>BACKENDS registry"]
            base["base.py<br/>PageBackend, FIGURE_MARKER"]
            text["pymupdf_text.py<br/>tiers 0 and 1"]
            llm["llm_markdown.py<br/>tier 2"]
            doc["docling.py<br/>tier 3"]
        end
    end
    scraper["scraper/pymupdf/pymupdf.py<br/>PyMuPDFScraper.scrape()"]

    scraper --> router & settings
    router --> signals & classify & binit & executors & settings
    executors --> settings
    init --> classify & signals & types & router
    signals --> classify & types
    classify --> types
    binit --> text & llm & doc & base
    text & llm & doc --> base
    text --> pymupdf[("pymupdf + pymupdf-layout<br/>required")]
    signals --> pymupdf
    llm --> p4llm[("pymupdf4llm + RapidOCR or Tesseract<br/>optional")]
    doc --> docling[("docling<br/>optional")]

```

| File | Role |
| --- | --- |
| `types.py` | `Tier` (an `IntEnum`, so tiers can be compared), the frozen `PageSignals`, and `PageOutcome` / `RouterResult` |
| `settings.py` | The `PDF_ROUTER_*` environment variables, read at call time |
| `signals.py` | `compute_signals(page)`: one `get_text("dict")`, image info, and PyMuPDF's layout model (skipped on scans) |
| `classify.py` | `classify(signals, *, scan_ocr_available)`: a pure rule table |
| `backends/base.py` | The `PageBackend` protocol (`available()`, `parse(pdf, pages)`) and `FIGURE_MARKER` |
| `backends/pymupdf_text.py` | `render_page(page, tables=…)`, shared by tiers 0 and 1. `_reuse_layout()` stops `find_tables()` from running the model again |
| `backends/llm_markdown.py` | Tier 2 (pymupdf4llm) and `scan_ocr_available()` |
| `backends/docling.py` | Tier 3: one Docling call per document, via a sub-PDF of the routed pages |
| `router.py` | `route_pdf(pdf, source_url) -> RouterResult`: stage 1, stage 2, the fallback chain, the time budget and the merge |
| `executors.py` | Long-lived pools per process (`spawn`): the shared pool, the Docling pool, the Docling slot, and waiter threads |

## Turning it off

**What's optional:** `pymupdf` 2.0 already installs pymupdf4llm and the layout model, so tiers 0–2 always work. Only OCR (`rapidocr`, or a system Tesseract) and Docling are optional: `pip install "gpt-researcher[pdf-router]"`. Without them, scanned pages come back as `page N: not extracted` markers. Docling checks the Hugging Face Hub for its models every time a converter starts, so offline deployments need `HF_HUB_OFFLINE=1`.

`PDF_ROUTER_ENABLED=false` sends PDFs back through the old path: one `PyMuPDFLoader` pass over the whole file, joined with `\n`. Other settings: `PDF_ROUTER_MAX_WORKERS` (default `min(4, cpu)`), `PDF_ROUTER_DOCLING_CONCURRENCY` (default 1), `PDF_ROUTER_DOC_TIMEOUT_S` (default 120) and `PDF_ROUTER_WORKER_MAX_TASKS` (default 200: a shared worker is replaced after that many tasks, which releases memory the native libraries never hand back; 0 = never).

## How the scraper calls it

```mermaid
flowchart TD
    A["PyMuPDFScraper.scrape()"] --> B{"PDF_ROUTER_ENABLED?"}
    B -->|"true, the default"| C{"URL or local path?"}
    C -->|"URL"| D["_download(): requests, timeout (5, 30),<br/>retry without SSL check on SSLError"]
    D --> E["join the streamed chunks into bytes"]
    C -->|"path"| F["read the file's bytes"]
    E & F --> G["route_pdf(bytes, link)"]
    G --> H["return (markdown, [], title)"]
    B -->|"false"| L["_scrape_with_loader(): download to a temp file,<br/>PyMuPDFLoader, remove the temp file"]
    L --> H2["return (text, [], title)"]
    D & G & L -.->|"any exception"| X["print it, return ('', [], '')"]
```

## Design: how a PDF goes through the router

```mermaid
flowchart TD
    A["PDF bytes + source URL"] --> L["Under MUPDF_LOCK: page count and title"]
    L --> S
    subgraph C1["Stage 1: shared process pool, chunks of 2 pages"]
        S["compute_signals(page)<br/>~8 ms text + ~140 ms layout model"] --> K["classify(signals)"]
        K -->|"tier 0 or 1"| R["render_page() right away<br/>reuses the page's layout result"]
    end
    K -->|"tier 2 or 3"| D{"Stage 2: which tier?<br/>not installed → next tier down"}
    D -->|"tier 2"| T2["pymupdf4llm<br/>shared pool, chunks of 2"]
    D -->|"tier 3, after every page is classified"| W["Waiter thread takes a Docling slot"]
    W --> T3["Docling pool: one call for all tier-3 pages<br/>timeout counted from the slot"]
    R --> M
    T2 --> M
    T3 --> M
    T2 & T3 -.->|"error, timeout or empty"| F["Fallback: one tier down"]
    F -.-> D
    M["Merge pages in order<br/>a page with no text gets a comment marker"] --> E{"Did every page fail?"}
    E -->|"yes"| Z["Return empty content:<br/>the scraper drops it"]
    E -->|"no"| O["Return Markdown + title<br/>log one summary line"]
```

- **Docling slot:** at most `PDF_ROUTER_DOCLING_CONCURRENCY` Docling jobs run at once, across all PDFs. A job's timeout (30 s + 10 s × pages) starts once it holds a slot, so waiting behind another PDF's job never times it out. On a timeout, the Docling pool is stopped and rebuilt, because a running task can't be cancelled.
- **Document budget:** `PDF_ROUTER_DOC_TIMEOUT_S` (default 120 s) bounds the whole call. When it runs out, finished pages are returned and pages still in flight get a "document time budget exceeded" marker.
- **Tier 0/1 failures:** if rendering fails or returns nothing in stage 1, the page also goes to the fallback chain (tier 1 → tier 0).
- **Worker recycling:** shared workers are replaced after `PDF_ROUTER_WORKER_MAX_TASKS` tasks (`max_tasks_per_child`). A replacement costs ~1.2 s plus the model load, so the default of 200 keeps it rare. Docling workers are not recycled: a restart costs 8–20 s, and that pool has its own reset on timeout.

### Classification rules (`classify.py`)

The rules are checked in order, and the first match wins.

```mermaid
flowchart TD
    P["PageSignals"] --> R1{"chars < 50 and<br/>img_cover >= 0.5?"}
    R1 -->|"yes: a scan"| OCR{"tier 2 has an OCR engine?<br/>RapidOCR or Tesseract data"}
    OCR -->|"yes"| T2a["Tier 2: LAYOUT"]
    OCR -->|"no"| T3a["Tier 3: DOCLING"]
    R1 -->|"no"| R2{"garbage >= 0.05?<br/>replacement chars or cid codes"}
    R2 -->|"yes: broken text layer"| T3b["Tier 3: DOCLING"]
    R2 -->|"no"| R3{"back_jump_ratio >= 0.15?"}
    R3 -->|"yes: stored out of reading order"| T2b["Tier 2: LAYOUT"]
    R3 -->|"no"| R4{"tables >= 1?<br/>layout model"}
    R4 -->|"yes"| T1["Tier 1: TABLES"]
    R4 -->|"no"| T0["Tier 0: PLAIN"]
```

`pictures` (figures found by the layout model) never changes the tier. Every tier replaces the text inside a figure with `<!-- figure -->` and keeps the caption.

### Fallback chain (`router.FALLBACK`)

A tier that raises an error, times out, returns no text or isn't installed hands the page to the next tier down. If stage 1 itself fails (signals or classification), its pages go to tier 0. Each attempt is recorded in `PageOutcome.reason`. The chain only goes down, and every tier writes the same figure marker, so the placeholder also covers a failed tier.

```mermaid
flowchart LR
    D3["Tier 3: Docling"] -->|"fails"| D2["Tier 2: pymupdf4llm<br/>if installed"]
    D3 -->|"fails, tier 2 not installed"| D0
    D2 -->|"fails"| D0["Tier 0: plain"]
    D1["Tier 1: tables"] -->|"fails"| D0
    D0 -->|"fails or empty"| X["Page comment:<br/>page N: not extracted (reason)"]
    S1["Stage 1: signals or classify"] -->|"fails"| D0
```

### Inside tiers 0 and 1 (`render_page`)

```mermaid
flowchart TD
    A["page with layout result<br/>runs get_layout() if missing"] --> B{"tier 1?"}
    B -->|"yes"| C["find_tables() with the reused layout result<br/>table.to_markdown(fill_empty=False)"]
    B -->|"no"| D
    C --> D["regions = tables + figure boxes"]
    D --> E["walk the dict blocks in stored order"]
    E --> F{"a region lies above this block,<br/>in the same column?"}
    F -->|"yes"| G["emit that region once:<br/>table Markdown or figure marker"]
    F -->|"no"| H
    G --> H{"for each line"}
    H -->|"rotated"| I["drop"]
    H -->|"centre inside a region"| J["drop the line, emit the region once"]
    H -->|"otherwise"| K["add to the paragraph<br/>join a line-end hyphen before lowercase"]
    K --> L["paragraphs joined by a blank line;<br/>regions never emitted are appended at the end"]
    J --> L
    I --> L
```

## Fixture flows

The tiers below were measured on the committed fixtures (`tests/fixtures/pdf/`), with OCR available (RapidOCR is installed here). The dashed arrows show what happens when an optional part is missing or a tier fails.

### `scanned-page.pdf` (1 page: a 1972 fax letter)

```mermaid
flowchart TD
    P1["p1: chars 0, img_cover 1.0<br/>layout model skipped"] --> S{"scan → OCR engine available?"}
    S -->|"yes, the default here"| T2["Tier 2: pymupdf4llm + RapidOCR<br/>~1.6 s"]
    S -.->|"no OCR engine"| T3["Tier 3: Docling OCR<br/>~6 s"]
    T2 --> OK["letter text: golden sentence, P.J. CROSS"]
    T3 --> OK
    T2 -.->|"fails"| T0["Tier 0: plain, no text layer"]
    T3 -.->|"fails, tier 2 installed"| T2
    T3 -.->|"fails, tier 2 not installed"| T0
    T0 -.-> X["every page failed → empty content<br/>(today's behaviour, now logged)"]
```

### `out-of-order-columns.pdf` (1 page, generated: two columns stored row by row)

Made with PyMuPDF by writing a two-column page one visual row at a time (left line 1, right line 1, left line 2, …), the way some Word and browser exports store text. The generator script was removed once the PDF was committed; it is in commit `0ad912ed`.

```mermaid
flowchart TD
    P1["p1: back_jump_ratio 0.344<br/>tables 0, pictures 0"] --> T2["Tier 2: pymupdf4llm<br/>~210 ms warm"]
    T2 --> OK["columns in reading order + headings"]
    T2 -.->|"pymupdf4llm missing or fails"| T0["Tier 0: plain"]
    T0 -.-> BAD["text still interleaved:<br/>a known degradation, logged"]
```

### `borderless-table.pdf` (RoBERTa, 13 pages, two columns, borderless tables)

```mermaid
flowchart TD
    D["13 pages, layout model on each"] --> A["p1–3, p10–12<br/>text only"]
    D --> B["p4–9, p13<br/>tables found"]
    A --> T0["Tier 0: plain, ~8 ms a page"]
    B --> T1["Tier 1: tables, ~350 ms a page<br/>p5: SEGMENT-PAIR row as Markdown"]
    T1 -.->|"fails"| T0b["Tier 0: plain<br/>table cells as loose lines"]
    D -.->|"layout model missing"| N["all 13 pages → tier 0<br/>no tables, a warning logged once"]
```

### `two-column-paper.pdf` (BERT, 16 pages, figures and tables)

```mermaid
flowchart TD
    D["16 pages, layout model on each"] --> A["p1–2, 4, 10–12, 14<br/>text only"]
    D --> F["p3, 5, 13, 15<br/>figures 1–4"]
    D --> B["p6–9<br/>tables"]
    D --> C["p16<br/>table + figure 5"]
    A --> T0["Tier 0: plain<br/>margin stamp on p1 dropped"]
    F --> T0f["Tier 0 + figure marker<br/>labels like E[CLS] dropped, caption kept"]
    B --> T1["Tier 1: tables"]
    C --> T1f["Tier 1: tables + figure marker"]
    T1 -.->|"fails"| T0
    T1f -.->|"fails"| T0f
    D -.->|"layout model missing"| N["all pages → tier 0:<br/>no tables, figure labels stay as loose text"]
```

### `mixed-document.pdf` (5 pages: BERT p1–2, the scan, RoBERTa p5–6)

```mermaid
flowchart TD
    D["5 pages"] --> A["p1–2: text"]
    D --> S["p3: scan<br/>chars 0, img_cover 1.0"]
    D --> B["p4–5: tables"]
    A --> T0["Tier 0: plain"]
    B --> T1["Tier 1: tables"]
    S --> O{"OCR engine available?"}
    O -->|"yes"| T2["Tier 2: OCR"]
    O -.->|"no"| T3["Tier 3: Docling"]
    T0 & T1 & T2 & T3 --> M["merge in page order:<br/>Left-to-right language model, then Permit me to introduce, then SEGMENT-PAIR"]
    T2 -.->|"fails → tier 0 finds no text"| X["p3 → page N: not extracted comment;<br/>the other 4 pages are still returned"]
```

## Before / after (this Mac)

Golden snippets passed (`tests/pdf_router/golden.py`, what a person reads on the page) and time per document. "Today" is `PyMuPDFScraper` before the router (`PDF_ROUTER_ENABLED=false`). Router times are warm. Docling times start a new converter per file, so they include its start-up. The full per-check table is in `tests/fixtures/pdf/probe-output/comparison.md`, regenerated with `python tests/pdf_router/tools/probe.py --docling --router`.

| Fixture | Pages | Today | Router | Docling |
| --- | --- | --- | --- | --- |
| borderless-table (RoBERTa) | 13 | 2/3, 0.62 s* | 3/3, 1.99 s | 3/3, 20.41 s |
| mixed-document | 5 | 1/4, 0.02 s | 4/4, 2.76 s | 4/4, 12.50 s |
| out-of-order-columns | 1 | 2/3, 0.00 s | 3/3, 0.43 s | 3/3, 2.37 s |
| scanned-page | 1 | 1/4, 0.00 s | 4/4, 1.60 s | 4/4, 6.31 s |
| two-column-paper (BERT) | 16 | 1/3, 0.04 s | 3/3, 1.82 s | 3/3, 12.73 s |
| **Total** | 36 | **7/17** | **17/17** | **17/17** |

\* The first file also pays for loading `PyMuPDFLoader`; the others take 0.02–0.04 s.

The router matches Docling on every check at 4–10× less time. It's slower than today's extractor, which skips layout: the cost is the layout model (~140 ms a page) plus the process pool. One gap remains against Docling: no `##` headings on tier-0 pages (0 against Docling's 34 on BERT).

## End to end with real URLs

Through the real `Scraper` (the path a research step uses, quality gates included), run with `python tests/pdf_router/tools/e2e.py`. Details: `probe-output/e2e-mac.md`, `e2e-linux-docker.md`.

| URL | Mac | Linux (Docker) | Result |
| --- | --- | --- | --- |
| arxiv.org/pdf/1810.04805.pdf (BERT, 16 pp) | 3.7 s | 8.5 s | 45 table rows, 5 figure markers |
| arxiv.org/pdf/1907.11692.pdf (RoBERTa, 13 pp) | 2.5 s | 5.4 s | 83 table rows |
| arxiv.org/pdf/1706.03762.pdf (Attention, 15 pp) | 3.5 s | 9.3 s | 32 table rows, 3 figure markers |
| arxiv.org/pdf/2005.14165.pdf (GPT-3, 75 pp) | 15.2 s | 37.5 s | 562 table rows; 14 pages to tier 2 |
| arxiv.org/pdf/1810.04805 (no `.pdf`) | 0.2 s | 0.4 s | `ArxivScraper`: abstract only, the router never runs |
| arxiv.org/pdf/0000.00000.pdf (404) | 0.3 s | 0.5 s | dropped, as before |
| **All six at once** | 18.3 s, peak 3.4 GB | 54.3 s, peak 2.8 GB | 5 kept |

Times include the download; the workers were already started. The output is identical on both platforms, character for character. The arXiv PDFs have no title in their metadata, so the title is `""`, as before.

**Scanned PDFs with no text layer** (National Archives JFK releases, pages are images only; today's extractor returns `""` for them, so the source is dropped):

| URL | Pages | Mac | Result |
| --- | --- | --- | --- |
| archives.gov/files/research/jfk/releases/177-10001-10080.pdf | 2 | 6.3 s | both pages OCR'd (pymupdf4llm + RapidOCR), 2,547 chars; readable, with garbled runs where the scan is poor |
| archives.gov/files/research/jfk/releases/177-10001-10180.pdf | 38 | 68.3 s | 36 pages OCR'd; pages 16 and 19 are grey cover sheets with no readable text and become `page N: not extracted` markers |

OCR costs ~1.8 s a page here, so the default 120 s document budget covers about 65 scanned pages; longer scans return what finished and mark the rest.

### One research run, before and after

A script (since removed; it is in commit `5b4d6dfc` and needs a paid API key) ran `GPTResearcher` on exactly BERT's and RoBERTa's PDFs (no web search), once with the router and once without. Query: "How does RoBERTa change BERT's pre-training, and how much do those changes matter on SQuAD and MNLI?" Reports and the number check: `probe-output/research-*.md`.

- **Both reports are correct on the numbers they quote,** for example RoBERTa 94.6 / 89.4 / 90.2 against BERT-large 90.9 / 81.8 / 86.6. The report without the router even rebuilt RoBERTa's Table 2 exactly.
- **On these two papers the router made no visible difference.** In these LaTeX PDFs, today's extractor keeps table cells in reading order, one per line, and the model can rebuild the table from that.
- **The router's gains are elsewhere:** scans (today's output is empty, so the source is dropped), text stored out of order, and figure noise. See "Before / after".
- **Cost:** $0.11 with the router, $0.14 without (the repo's own estimates). With one run each, that difference is within noise.

## Measured cost per page (this Mac)

| Step | Cost |
| --- | --- |
| Signals (text + layout model) | ~150 ms median; layout model skipped on scans |
| Tier 0 (once the layout result is known) | ~8 ms |
| Tier 1 | ~350 ms median on table pages, mostly `table.to_markdown()`; ~8 ms on other pages |
| Tier 2 | ~210 ms warm, ~1 s cold; a scan ~1.6 s |
| Tier 3 | ~780 ms warm; ~8 s for the first call in a process |

### Whole documents (`route_pdf`, 4 shared workers, chunks of 2, warm, best of 3)

| Fixture | Pages | Time | Backends used |
| --- | --- | --- | --- |
| `two-column-paper` (BERT) | 16 | 1.84 s | plain 11, tables 5 |
| `borderless-table` (RoBERTa) | 13 | 1.84 s | plain 6, tables 7 |
| `mixed-document` | 5 | 2.24 s | plain 2, OCR 1, tables 2 |
| `scanned-page` | 1 | 1.59 s (OCR); 4.9 s via Docling, 15.6 s cold | pymupdf4llm, or docling without OCR |
| `out-of-order-columns` | 1 | 0.18 s | pymupdf4llm |

The first PDF in a process also pays ~1.2 s per worker to start (`spawn` re-imports the `gpt_researcher` package).

Memory per process (resident): shared worker ~260 MB at start, ~650–870 MB after parsing text PDFs, ~830–900 MB once it has also run OCR; Docling worker ~1.3 GB.

**Tried and rejected (2026-10-25): a dedicated OCR pool.** The idea was to keep OCR's models out of the shared workers by sending scanned pages to their own one-worker pool. Measured on the same machine, same documents: the 38-page scan went from 54.4 s to 62.5 s (four shared workers doing OCR were only 13% faster than one, so contention is real, but one worker still loses), and the six-URL peak went from 3.32 GB to 4.15 GB, because OCR adds only ~200–300 MB to a shared worker while the extra process holds ~1.1 GB and sits idle between scans. Reverted; an OCR worker that shuts down when idle is on the "another week" list.
