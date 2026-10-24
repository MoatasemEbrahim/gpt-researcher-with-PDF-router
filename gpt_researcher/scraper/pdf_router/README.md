# PDF page router

The router classifies each page of a PDF and parses it with the cheapest backend that can handle it. The pages are merged back into one Markdown string, which `PyMuPDFScraper` returns through the existing `(content, image_urls, title)` contract.

Status: signals, classification and the four backends are built (Phases 2–3). The router, executors and fallback (Phase 4) and the scraper wiring (Phase 5) are **planned**, so parts of the diagrams below are marked *planned*.

## Structure

```mermaid
flowchart LR
    subgraph pkg["gpt_researcher/scraper/pdf_router/"]
        init["__init__.py<br/>exports"]
        types["types.py<br/>Tier, PageSignals"]
        signals["signals.py<br/>compute_signals()"]
        classify["classify.py<br/>is_scan(), classify()"]
        router["router.py<br/>route_pdf() · planned"]:::planned
        executors["executors.py<br/>process pools · planned"]:::planned
        subgraph backends["backends/"]
            binit["__init__.py<br/>BACKENDS registry"]
            base["base.py<br/>PageBackend, FIGURE_MARKER"]
            text["pymupdf_text.py<br/>tiers 0 and 1"]
            llm["llm_markdown.py<br/>tier 2"]
            doc["docling.py<br/>tier 3"]
        end
    end
    scraper["scraper/pymupdf/pymupdf.py<br/>PyMuPDFScraper · wiring planned"]:::planned

    scraper -.-> router
    router -.-> signals & classify & binit & executors
    init --> classify & signals & types
    signals --> classify & types
    classify --> types
    binit --> text & llm & doc & base
    text & llm & doc --> base
    text --> pymupdf[("pymupdf + pymupdf-layout<br/>required")]
    signals --> pymupdf
    llm --> p4llm[("pymupdf4llm + RapidOCR or Tesseract<br/>optional")]
    doc --> docling[("docling<br/>optional")]

    classDef planned stroke-dasharray: 5 5
```

| File | Role |
| --- | --- |
| `types.py` | `Tier` (an `IntEnum`, so tiers can be compared) and the frozen `PageSignals` dataclass |
| `signals.py` | `compute_signals(page)`: one `get_text("dict")`, image info, and PyMuPDF's layout model (skipped on scans) |
| `classify.py` | `classify(signals, *, scan_ocr_available)`: a pure rule table |
| `backends/base.py` | The `PageBackend` protocol (`available()`, `parse(pdf, pages)`) and `FIGURE_MARKER` |
| `backends/pymupdf_text.py` | `render_page(page, tables=…)`, shared by tiers 0 and 1. `_reuse_layout()` stops `find_tables()` from running the model again |
| `backends/llm_markdown.py` | Tier 2 (pymupdf4llm) and `scan_ocr_available()` |
| `backends/docling.py` | Tier 3: one Docling call per document, via a sub-PDF of the routed pages |

## Design: how a PDF goes through the router

```mermaid
flowchart TD
    A["PDF bytes + source URL"] --> B["Split the pages into chunks"]
    B --> C["Stage 1, per chunk, in the shared process pool · planned"]
    subgraph C1["Stage 1 worker"]
        S["compute_signals(page)<br/>~8 ms text + ~140 ms layout model"] --> K["classify(signals)"]
        K -->|"tier 0 or 1"| R["render_page() right away<br/>reuses the page's layout result"]
        K -->|"tier 2 or 3"| Q["return the page number"]
    end
    C --> S
    R --> M
    Q --> D{"Stage 2: which tier? · planned"}
    D -->|"tier 2"| T2["pymupdf4llm<br/>shared pool, chunked"]
    D -->|"tier 3"| T3["Docling<br/>dedicated single worker,<br/>one call for all tier-3 pages"]
    T2 --> M
    T3 --> M
    T2 -.->|"error or timeout"| F["Fallback chain"]
    T3 -.->|"error or timeout"| F
    F --> M["Merge pages in order, joined by a blank line"]
    M --> E{"Did every page fail?"}
    E -->|"yes"| Z["Return empty content:<br/>the scraper drops it"]
    E -->|"no"| O["Return Markdown + title"]

    classDef planned stroke-dasharray: 5 5
    class C,D planned
```

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

### Fallback chain (planned, Phase 4)

A tier that raises an error, times out or isn't installed hands the page to the next tier down. The chain only goes down, and every tier writes the same figure marker, so the placeholder also covers a failed tier.

```mermaid
flowchart LR
    D3["Tier 3: Docling"] -->|"fails"| D2["Tier 2: pymupdf4llm<br/>if installed"]
    D3 -->|"fails, tier 2 not installed"| D0
    D2 -->|"fails"| D0["Tier 0: plain"]
    D1["Tier 1: tables"] -->|"fails"| D0
    D0 -->|"fails or empty"| X["Page comment:<br/>page N: not extracted (reason)"]
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

## Measured cost per page (this Mac)

| Step | Cost |
| --- | --- |
| Signals (text + layout model) | ~150 ms median; layout model skipped on scans |
| Tier 0 (once the layout result is known) | ~8 ms |
| Tier 1 | ~350 ms median on table pages, mostly `table.to_markdown()`; ~8 ms on other pages |
| Tier 2 | ~210 ms warm, ~1 s cold; a scan ~1.6 s |
| Tier 3 | ~780 ms warm; ~8 s for the first call in a process |
