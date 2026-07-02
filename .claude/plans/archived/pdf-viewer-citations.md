# Plan: Inline PDF viewer + annotations, and page-level citations

## Context

When viewing an uploaded source, Open Notebook shows the **extracted markdown** of the PDF, not the
PDF itself. The user wants (1) to **see and interact with the real PDF** — including **highlight/comment
annotations** — and (2) AI answers whose **citations are actually referable to a specific location**
(page) in the source.

This was scoped via Q&A:
- **PDF interaction:** *View + annotate* (inline viewer + highlights/comments saved to DB, re-rendered as overlay).
- **Citation precision:** *PDF page-level* (citation jumps to the exact page in the viewer).
- **Extraction engine:** *Docling*.

Grounded findings from the codebase (verified 2026-06-21):

- **Original PDFs are retained** on disk at `data/uploads/`; path in `Source.asset.file_path`; served by
  `GET /sources/{id}/download` (`api/routers/sources.py:702-716`, + HEAD + `file_available` flag). A viewer is feasible.
- **Current display:** `frontend/src/components/source/SourceDetailContent.tsx:523-548` renders `source.full_text`
  via `react-markdown` in the "Content" tab. A download button already exists (~268-303). No PDF.js anywhere.
- **Citation scaffolding already exists end-to-end** — prompts emit `[source:id]` / `[note:id]` / `[insight:id]`
  (`prompts/chat/system.jinja`, `prompts/ask/query_process.jinja`, `prompts/source_chat/system.jinja`); the frontend
  parses them into numbered, clickable refs (`frontend/src/lib/utils/source-references.tsx`, `ChatPanel.tsx`).
  **Gap is granularity, not plumbing.**
- **No positional metadata today.** Chunks live in `source_embedding` with `order` (chunk index), `content`,
  `embedding`, `source` — but `fn::vector_search` (`migrations/4.surrealql:75-133`) does **not** return `order`,
  and **no page number / char offset is stored at all** (`migrations/1.surrealql`).
- **content-core** (v1.14.1) default PDF engine is **PyMuPDF/`fitz`** (`processors/pdf.py`, AGPL, already a
  transitive dep) which flattens pages to one string. It **also ships a Docling wrapper** (`processors/docling.py`,
  `document_engine: auto|simple|docling`, JSON output supported) — but the `docling` package itself is **NOT installed**
  (pyproject pulls plain `content-core`, not the `[docling]` extra; not in `uv.lock`).

## Decisions (defaults taken — veto any at review)

- **Viewer lib:** `@react-pdf-viewer` (MIT, has highlight plugin for the annotation phase). Fallback `react-pdf`
  if React 19 / Next 16 peer-dep issues. Configure the PDF.js worker for Next 16.
- **Extraction engine:** **Docling** (MIT). Gives better markdown AND per-block `page_no` + `bbox` provenance →
  exact page numbers (no fuzzy matching) and powers coordinate highlight/annotation anchoring later.
  - **Rejected Marker** — GPL-3.0 code + OpenRAIL-M model license ($2M revenue cap, commercial self-host needs a
    license) + ~5GB VRAM/GPU. Bad fit for an MIT, freely self-hostable, privacy-first project.
  - PyMuPDF (`fitz`) stays as the lightweight fallback (already present; AGPL already transitive).
- **Citation token:** `[source:<id>#p=<n>]` — extends the existing `[source:id]` format so old citations keep working.
- **Annotations are global** (auth is dev-only single-user); add a `user` field later if real auth lands.

## Deploy target

The DGX Spark (`ssh spark`, host `spark-d41f`, **Linux aarch64 + NVIDIA GPU**, repo already checked out at `~/learn`).
GPU box → ideal for the Docling pipeline. Note: ARM64 + CUDA, so Phase 2's PyTorch/Docling install needs aarch64+CUDA wheels.

---

## Phase 1 — Inline PDF viewer (read-only)   [no backend changes]

- Add `@react-pdf-viewer`; **validate it builds on React 19 / Next 16** (fallback `react-pdf` + custom highlight layer).
- New `frontend/src/components/common/PDFViewer.tsx` — fetch binary via `sourcesApi.downloadFile(sourceId)`.
- In `SourceDetailContent.tsx` (Content tab ~line 523) add a **"Rendered / Original PDF" toggle**; show the PDF tab
  only when `file_available && asset is a PDF`, else keep the markdown rendering.
- Page navigation + in-document search.
- **Ships:** the real PDF view (the original complaint) + de-risks the viewer lib before Phase 4 depends on it.

## Phase 2 — Docling extraction upgrade   [foundation for Phase 3]

- Add `docling` dependency (verify model-weights license; pre-bake model download into the Docker image).
- In `open_notebook/graphs/source.py` (`content_process`/`save_source`, ~34-140): for PDFs run Docling once and capture
  **both** markdown `full_text` and per-block `(text, page_no, bbox)` from `result.document` provenance. Keep `fitz` as fallback.
- Validate Docling CPU/GPU perf + extraction quality on real user PDFs (do this on the Spark).
- Add a **re-extract / backfill** command for existing sources.
- **Ships:** much more faithful rendered markdown + the metadata foundation.

## Phase 3 — Page-level citations   [needs Phase 2]

- **Migration:** add `page_number` (option<int>), optionally `bbox`/`prov` (option<object>), to `source_embedding`. Bump version.
- **Provenance-aware chunking** (`open_notebook/utils/chunking.py`, `commands/embedding_commands.py`): tag each chunk with its
  real `page_no`; store `page_number` per `source_embedding` record.
- **Search:** update `fn::vector_search` (`migrations/4.surrealql`) and `vector_search()` (`open_notebook/domain/notebook.py:738-768`)
  to return `order` + `page_number` (+ bbox).
- **Prompts:** attach the page to each retrieved passage; instruct the model to copy it as `[source:<id>#p=<n>]` (never guess).
- **Frontend:** extend the ref parser (`source-references.tsx`) to capture `#p=N`; clicking opens the PDF viewer at that page.
- Re-embed existing PDFs to backfill page numbers.
- **Ships:** citations jump to the exact page. Exact (provenance) — the fuzzy-matching risk is gone.

## Phase 4 — PDF annotations (highlight + comment)   [needs Phase 1]

- **DB:** new `source_annotation` table (`source` record<source>, `page` int, normalized rect/bbox object, `color`, `note` string,
  `quote`/`selected_text` string, `created`). Migration + domain model in `open_notebook/domain/`.
- **API:** CRUD — `GET /sources/{id}/annotations`, `POST`, `PATCH/PUT /annotations/{id}`, `DELETE /annotations/{id}` + service.
- **Frontend:** wire the `@react-pdf-viewer` highlight plugin — selection → rects → save via API; re-render saved annotations as
  overlay on load; sidebar list that jumps to each highlight. Reuse the same normalized-coordinate model as Phase 3 bboxes.

---

## Status

As of 2026-06-21: scoping complete (view+annotate; page-level citations; Docling). Plan + 4-task to-do list created.
**Nothing built yet.** Phases 1 and 2 are independent starting points; recommended start = **Phase 1** (fast, no migrations,
de-risks the viewer lib).

## Main risks

- `@react-pdf-viewer` React 19 / Next 16 peer-dep compatibility (validate in Phase 1).
- Docling weight on self-hosters (model download, PyTorch) — mitigate by pre-baking into the Docker image; the Spark has a GPU.
- Docling model-weights license — confirm permissive before committing the dependency.
