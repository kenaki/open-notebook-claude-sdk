# Document Foundation — Standalone Phases (PDF Viewer + Citations + Annotations)

> **Self-contained plan for standalone phases.** Read `coordinator.md` (this directory) first —
> shared decisions, conventions, file ownership — then execute the specific phase in this file.
> **Phase1 is independent** (no deps; run any time, even concurrently with A, B, C).
> **Phase3 depends on A2 ☑** (needs `page_map`) and ideally **Phase1 ☑** (citation click → PDF open).
> **Phase4 is DEFERRED** — spec is here for reference; do NOT schedule until Phase1 + Phase3 ☑.
> **Location:** `.claude/plans/document-foundation/standalone.md` → archived with the directory
> when all build-now phases ☑.

---

## Phase1 — Inline PDF Viewer (FE-only, no migration, no backend changes)

### SESSION HANDOFF

**Deps:** none — **fully independent.** Can run concurrently with Track A, B, or C.

**Paste-able resume prompt (run in a fresh chat):**
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/standalone.md — the Phase1 section only. Implement Phase1
(PDFViewer component + SourceDetailContent PDF tab integration). Verify: npm run build passes;
manually open a source with a PDF asset in the browser → the "Original PDF" tab renders the PDF with
navigation. Commit. Update BOTH the standalone Status table below AND the coordinator's Global status
table + Changelog. Announce "✅ Phase1 complete — safe to clear context. Next: Phase3 (after A2 ☑)."
Stop.
```

**State at handoff (2026-06-26):** Not started.

### File ownership (Phase1)

| File | What changes |
|------|-------------|
| `frontend/package.json` (or `package.json` at root) | Add `@react-pdf-viewer` (MIT). Validate React 19/Next 16 peer-deps; fallback to `react-pdf` if peer-dep fails. |
| `frontend/src/components/common/PDFViewer.tsx` | New component: wraps @react-pdf-viewer; fetches binary via `sourcesApi.downloadFile(sourceId)` |
| `frontend/src/components/source/detail/SourceDetailContent.tsx` | Add a new "Original PDF" tab (TabsTrigger + TabsContent) that renders `<PDFViewer>` — show only when `source.asset?.file_path` exists and the asset is a PDF |
| `frontend/src/lib/locales/*/` | Locale keys for "Original PDF" tab label, "Loading PDF...", etc. |

**Do NOT touch:** `SourceContentTab.tsx` (C3 owns that), `api/*`, `open_notebook/*`.

### Spec

**Dependency install:**
```bash
# In frontend/
npm install @react-pdf-viewer/core @react-pdf-viewer/default-layout pdfjs-dist
```
- Verify React 19 peer-dep compatibility. If `@react-pdf-viewer` has a hard React ≤18 peer dep:
  - Try `--legacy-peer-deps`; confirm it still builds and runs.
  - If it fails at runtime, fall back to `react-pdf` + a custom page-navigation layer.
- Configure the PDF.js worker for Next.js 16 (add to `next.config.js` / webpack config):
  ```js
  webpack: (config) => {
    config.resolve.alias['pdfjs-dist/build/pdf.worker.min.js'] =
      'pdfjs-dist/build/pdf.worker.min.mjs'  // or the correct Next16 path
    return config
  }
  ```

**`PDFViewer.tsx`** (`frontend/src/components/common/PDFViewer.tsx`):
```tsx
'use client'
import { Worker, Viewer } from '@react-pdf-viewer/core'
import { defaultLayoutPlugin } from '@react-pdf-viewer/default-layout'
import '@react-pdf-viewer/core/lib/styles/index.css'
import '@react-pdf-viewer/default-layout/lib/styles/index.css'
import { sourcesApi } from '@/lib/api/sources'
import { useEffect, useState } from 'react'

interface PDFViewerProps {
  sourceId: string
  initialPage?: number   // Phase3 will use this for citation jumps
}

export function PDFViewer({ sourceId, initialPage = 0 }: PDFViewerProps) {
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const layoutPlugin = defaultLayoutPlugin()

  useEffect(() => {
    // fetch binary via sourcesApi.downloadFile → create object URL
    sourcesApi.downloadFile(sourceId).then(blob => {
      setPdfUrl(URL.createObjectURL(blob))
    })
    return () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl) }
  }, [sourceId])

  if (!pdfUrl) return <div>Loading PDF...</div>

  return (
    <Worker workerUrl="/pdf.worker.min.js">  {/* adjust path per Next.js public/ setup */}
      <div style={{ height: '80vh' }}>
        <Viewer fileUrl={pdfUrl} plugins={[layoutPlugin]} initialPage={initialPage} />
      </div>
    </Worker>
  )
}
```

> **Note for Phase3:** `initialPage` prop is pre-wired here so Phase3 can drive citation-jump by
> just passing `initialPage={pageNumber}` — no PDFViewer changes needed in Phase3.

**`SourceDetailContent.tsx`** — add a new tab:
- In the `TabsList`, add a new `TabsTrigger value="pdf"` after the existing "Content" trigger.
- Show only when `source.asset?.file_path && isPdfAsset(source)` — add a small helper:
  ```ts
  const isPdfAsset = (source: SourceDetailResponse) =>
    source.asset?.file_path?.toLowerCase().endsWith('.pdf') ?? false
  ```
- In `TabsContent value="pdf"`:
  ```tsx
  <TabsContent value="pdf">
    <PDFViewer sourceId={source.id} />
  </TabsContent>
  ```
- Locale key: `sources.viewPdf` = "Original PDF".

### Verify (Phase1)
1. `npm run build` passes with no TypeScript or webpack errors.
2. Open a source that has a PDF asset in the browser → the "Original PDF" tab appears and is clickable.
3. The PDF renders inline with page navigation (next/prev page, zoom, search).
4. For sources without a PDF asset (web page, pasted text), the "Original PDF" tab does NOT appear.
5. No regressions in the "Content" tab or other tabs.

---

## Phase3 — Page-level citations (migration 20 + provenance-aware chunks + #p=N tokens)

### SESSION HANDOFF

**Deps:** **A2 must be ☑** (needs `page_map` in SourceState) + **A3 must be ☑** (needs chunking pipeline that Phase3 modifies) + **Phase1 recommended ☑** (citation-click → PDF open requires PDFViewer).
**⚠ Ordering vs Track B:** Phase3 now edits `open_notebook/graphs/source.py` (persist `page_map` — see design note below), which **B2** also edits (fire-and-forget triggers). **Never run Phase3 and B2 concurrently**; whichever runs first completes before the other starts (coordinator shared-file table updated 2026-07-02).

**Paste-able resume prompt (run in a fresh chat):**
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/standalone.md — the Phase3 section only. Confirm A2 ☑, A3 ☑, and
Phase1 ☑ in the coordinator before starting. Implement Phase3 (migration 20 + provenance chunking +
citation tokens + FE ref parser). Verify: API restart → migration 20 applied; re-embed a PDF → rows
carry page_number; a citation [source:id#p=3] in chat scrolls PDFViewer to page 3. Commit. Update
BOTH the standalone Status table AND the coordinator's Global status table + Changelog. Announce
"✅ Phase3 complete — safe to clear context." Stop.
```

**State at handoff (2026-06-26):** Not started. A2, A3, Phase1 not yet done.

### File ownership (Phase3)

**NOTE:** Phase3 extends files that Track A3 created/modified. Edit ONLY after A3 ☑.

| File | What changes |
|------|-------------|
| `open_notebook/database/migrations/20.surrealql` | Migration 20: `source.page_map` (persisted provenance) + page_number/bbox on source_embedding; update fn::vector_search |
| `open_notebook/database/migrations/20_down.surrealql` | Down migration |
| `open_notebook/database/async_migrate.py` | Append mig 20 to up + down lists (AFTER A1 ☑ appended mig 19) |
| `open_notebook/graphs/source.py` | `save_source` persists `state.page_map` → `source.page_map` (⚠ B2 also edits this file — never same wave) |
| `open_notebook/domain/notebook.py` (Source model) | `page_map: Optional[list] = None` field + nullable (⚠ Track B owns this file after A — coordinate ordering with B chunks) |
| `open_notebook/utils/chunking.py` | Tag each chunk with its page_number from the persisted page_map (AFTER A3 ☑) |
| `commands/embedding_commands.py` | `embed_source` reads `source.page_map`, stores page_number per source_embedding row; `backfill_page_numbers` command (AFTER A3 ☑) |
| `open_notebook/database/migrations/4.surrealql` | Update `fn::vector_search` to return page_number + bbox |
| `prompts/chat/system.jinja` | Instruct model to emit [source:\<id\>#p=\<n\>] for page-cited passages |
| `prompts/ask/query_process.jinja` | Same citation token instruction |
| `frontend/src/lib/utils/source-references.tsx` | Extend ref parser to capture #p=N; citation-click opens PDFViewer at that page |

### Spec

**Design note (resolves Q-page-map-provenance, 2026-07-02):** `page_map` (Docling per-block `(text,
page_no)` from A2) is **transient graph state** — but `embed_source` is a fire-and-forget command that
runs out-of-process and reads only the DB, so it can NEVER see graph state; the same is true of any
backfill (A3's `build_sections` already hit this and fell back to page-text search). Stamping
`page_number` therefore requires **persisting `page_map`** at ingest. Migration 20 adds
`source.page_map`; the graph's `save_source` node writes `state.page_map` when A2 extraction produced
one; `chunk_text`/`embed_source` read it back off the source record. This makes the ingest path AND the
backfill path work from the same persisted provenance.

**`migrations/20.surrealql`:**
```surql
-- Migration 20: document-foundation Phase3 — page provenance

-- Persisted per-block page provenance from extraction (A2). Null for non-PDF / pre-Docling sources.
-- Array of {page_no: int, text_prefix: string, char_start: int, char_end: int}-shaped objects
-- (exact block shape = whatever A2's _extract_docling_page_map emits; stored opaquely).
DEFINE FIELD IF NOT EXISTS page_map    ON TABLE source FLEXIBLE TYPE option<array>;

DEFINE FIELD IF NOT EXISTS page_number ON TABLE source_embedding TYPE option<int>;
DEFINE FIELD IF NOT EXISTS bbox        ON TABLE source_embedding FLEXIBLE TYPE option<object>;
```

Also update `fn::vector_search` in `migrations/4.surrealql` to `SELECT ...existing fields..., page_number, bbox` — or, preferably, create a new migration that redefines the function (if SurrealDB supports `DEFINE FUNCTION IF NOT EXISTS` or `REMOVE FUNCTION` + redefine). If editing migration 4 is risky, add a separate function `fn::vector_search_v2` in migration 20 and update callers.

`vector_search()` in `open_notebook/domain/notebook.py:744–774` — update Python call to expect `page_number` and `bbox` in results.

**`migrations/20_down.surrealql`:**
```surql
REMOVE FIELD page_map    ON TABLE source;
REMOVE FIELD page_number ON TABLE source_embedding;
REMOVE FIELD bbox        ON TABLE source_embedding;
```

**Persist at ingest** (`graphs/source.py` + `domain/notebook.py`):
- Add `page_map: Optional[list] = None` to the `Source` model (+ `nullable_fields`).
- In `save_source` (the node that writes `full_text`, `graphs/source.py:110–140`): when
  `state.page_map` exists, set `source.page_map = state.page_map` in the same save. No page_map (web
  page, pasted text, PyMuPDF-fallback without provenance) → field stays null and everything downstream
  degrades to null `page_number` (current behavior).

**Provenance-aware chunking** in `utils/chunking.py` and `commands/embedding_commands.py`:
- `chunk_text()` already splits text into chunks. After A3, each chunk knows its `section`.
- In Phase3: `embed_source` loads `source.page_map` from the record (NOT from graph state) and records
  the `page_number` of each chunk's dominant page — match chunk text/offsets against the `page_map`
  entries (e.g. the page_no of the first entry whose text overlaps the chunk's start).
- Store `page_number` on each `source_embedding` insert.

**Backfill:** add a `backfill_page_numbers` command that re-embeds existing PDF sources to stamp
`page_number` on old `source_embedding` rows. Provenance resolution order: (1) `source.page_map` if
persisted; (2) if null and the PDF asset file still exists, re-extract the page_map (A2's
`_extract_docling_page_map`, PyMuPDF fallback) and persist it first; (3) neither → leave `page_number`
null (never guess). One-time operation; run manually.

**Prompts** (`prompts/chat/system.jinja`, `prompts/ask/query_process.jinja`):
- Append to the retrieved-passage formatting: "For each retrieved passage, if a `page_number` is available, cite it as `[source:<source_id>#p=<page_number>]`. Never guess a page number."
- Keep existing `[source:id]` / `[note:id]` / `[insight:id]` instructions intact.

**Frontend ref parser** (`frontend/src/lib/utils/source-references.tsx`):
- Extend the existing `[source:id]` regex to also match `[source:id#p=N]`.
- On click of a `#p=N` citation: if the source detail modal is open for that source, call a handler that sets `PDFViewer`'s page (pass `initialPage` prop or use a ref/callback). If the modal isn't open, open it with `initialPage=N`.
- Backward compat: existing `[source:id]` without `#p=N` keeps working as today.

### Verify (Phase3)
1. API restart → logs show `migration 20 applied` and version bumped to 20.
2. Ingest a fresh PDF → the `source` record has a non-null `page_map`; its `source_embedding` rows have a non-null `page_number`. Backfill an OLD source (no persisted page_map, file present) → page_map persisted + rows stamped; file absent → rows stay null, no crash.
3. Chat over a PDF source → the AI emits `[source:id#p=3]`-style citations (not just `[source:id]`).
4. Clicking a `[source:id#p=3]` citation in the chat → PDFViewer opens at page 3.
5. Existing `[source:id]` citations (without `#p=N`) still work as before.
6. `uv run pytest tests/` — green.
7. `npm run build` — green.

---

## Phase4 — PDF Annotations (DEFERRED — do not implement until Phase1 + Phase3 ☑)

> **This phase is documented here for reference.** Do NOT schedule it as a blocking chunk.
> Execute only after Phase1 and Phase3 are both ☑ and the user explicitly requests Phase4.

### Scope (Phase4)

- **DB:** new `source_annotation` table (migration 21).
  - Fields: `source record<source>`, `page int`, `rect object` (normalized 0–1 coordinates), `color string`, `note string`, `quote string`, `created datetime`.
  - SCHEMAFULL; `quote` is the selected text; `note` is the comment.
- **API:** CRUD endpoints in `api/routers/sources/annotations.py` (new file, wire in `__init__.py`):
  - `GET /sources/{id}/annotations` → `List[AnnotationResponse]`
  - `POST /sources/{id}/annotations` → create
  - `PATCH /annotations/{id}` → update note/color
  - `DELETE /annotations/{id}` → delete
- **Frontend:** wire the `@react-pdf-viewer` highlight plugin:
  - Selection in PDFViewer → normalized rect → `POST /annotations` → re-render overlay.
  - On load: `GET /annotations` → render saved highlights as overlay.
  - Sidebar: list of annotations that jump to the highlight on click.
  - Reuse the bbox/rect model from Phase3.
- **Auth:** global (no user field in v1; add later when real auth lands).
- **Annotation → chat:** clicking an annotation highlight opens a "Chat about this highlight" action (reuse PassageSelectionMenu pattern).

### Status (Phase4)

| Phase | Title | Status | Notes |
|-------|-------|--------|-------|
| Phase4 | Annotations (source_annotation, mig 21, highlight plugin) | ⊘ | **DEFERRED** — do not start until Phase1 + Phase3 ☑ |

---

## Status table (all standalone phases)

| Phase | Title | Status | Notes |
|-------|-------|--------|-------|
| Phase1 | PDFViewer.tsx inline viewer (FE-only) | ☑ | commit 1608053; @react-pdf-viewer/core+default-layout+pdfjs-dist, PDFViewer.tsx, Original PDF tab in SourceDetailContent, next.config worker alias, 14 locales. ⚠ browser render spot-check still pending (manual) |
| Phase3 | page_number/bbox + vector_search + #p=N citations (mig 20) | ◐ | commit b525c88 (wave5 2026-07-02); code landed + static-verified. **Live spot-checks parked** (migration-apply + fn::vector_search redefine, re-embed→page_number, chat #p=N emission, citation→PDF click, npm build). Citation-click final wiring → C4 (parser forwards `page`) |
| Phase4 | Annotations (source_annotation, mig **22**, highlight plugin) | ☑ | commit 83ecb9a (2026-07-04 finish run). Mig 22 applied live (DB positional v22, no comment-swallow); live CRUD round-trip PASS (POST 201→GET→PATCH→DELETE); `@react-pdf-viewer/highlight@3.12`, rect = HighlightArea[] percentages verbatim; sidebar + popover + chat-about-highlight (full source page only, mirrors existing modal pattern). ⚠ visual browser smoke on punch-list. |

Legend: ☐ todo · ◐ in progress · ☑ done · ⊘ deferred

---

## Changelog (standalone phases)

- 2026-07-02 (wave5) — **Phase3 ◐ (commit b525c88)** — page-level citations landed in an orchestrated
  run. Migration 20: `source.page_map` (FLEXIBLE option<array>) + `source_embedding.page_number`
  (option<int>) + `bbox` (option<object>); `fn::vector_search` redefined in mig 20 via `REMOVE FUNCTION IF
  EXISTS` + `DEFINE FUNCTION IF NOT EXISTS` (same idempotent pattern mig 4 uses — mig 4 left untouched),
  projecting `page_number`/`bbox` through the grouped RETURN. `save_source` persists `state.page_map` at
  ingest; `chunk_text`/`embed_source` read it off the DB record and stamp `page_number` per chunk
  (`build_page_char_map`/`find_chunk_page`, mirroring A3's monotonic-search; never guesses — null when
  unmatched). `backfill_page_numbers` command re-embeds old PDFs (provenance order: persisted page_map →
  re-extract if file present → leave null). Prompts (`chat/system.jinja`, `ask/query_process.jinja`) now
  instruct `[source:id#p=N]` emission. `source-references.tsx` parses `#p=N`, round-trips it through the
  markdown href as `?p=N`, and calls `onReferenceClick(type, id, page)`. **Left ◐** — Verify block is live
  (migration-apply on API restart, real-PDF re-embed, browser citation click, npm build); on the punch-list.
  `bbox` stays null (A2's page_map has no bbox — the column exists for Phase4). **B2 unblocked** (source.py freed).
