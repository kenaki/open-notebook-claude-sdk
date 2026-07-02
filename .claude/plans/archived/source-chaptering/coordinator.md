# Source Chaptering + Verify-Clean + Summaries + Document Interaction — Coordinator / Index

> **Shared source of truth for a multi-track plan.** This file holds everything common to all tracks.
> Each track is executed from its own file (`<track>.md` in this directory) by its own chat.
> A track chat reads THIS file first, then owns exactly one track file.
> **Location:** `.claude/plans/source-chaptering/coordinator.md` → the whole directory is archived to
> `.claude/plans/archived/source-chaptering/` once every track is ☑.

## How to run this plan (read first)
1. Pick a track whose deps are ☑ in the Global status table below and whose row is **runnable now**.
2. Open its file (`a-foundation.md`, `b-pipeline.md`, `c-surfaces.md`) in a fresh chat; that file is self-contained.
3. **Track A must land first.** Once A is ☑, Tracks **B and C run concurrently** in separate chats (disjoint files).
4. One chunk per session. On each chunk completion, update BOTH the track file's status AND the Global
   status table here, then announce "safe to clear context" and stop.

## Concurrency matrix
| Track | File | Depends on (must be ☑) | Concurrent with | Sequential after | Why |
|-------|------|------------------------|-----------------|------------------|-----|
| A — Foundation (data + extraction + chaptering) | `a-foundation.md` | — | — | — | head of critical path; B & C both build on its data model + `Source.get_sections` |
| B — Backend pipeline (verify → summaries → tiered context → tools) | `b-pipeline.md` | **A** | **C** | A | extends `notebook.py`/`source.py`/`commands/` that A created |
| C — Surfaces (API + frontend) | `c-surfaces.md` | **A** | **B** | A | touches only `api/*` + `frontend/*` — disjoint from B |
> Read as: `A` first, alone. Then `B ‖ C` together. B and C share **no files** (B = backend domain/graph/commands/ai; C = api routers + frontend), so they are safe to run at the same time once A is ☑.

## Shared-file ownership (conflict map)
| File | Owning track(s) | Wait order | Note |
|------|-----------------|-----------|------|
| `open_notebook/domain/notebook.py` | A then B | A ☑ before B edits | A adds `SourceSection` model + `Source.get_sections/get_outline` + `page_offset`; B edits `get_context`/adds summarize+cleaned helpers. **C must NOT touch it** (C reads it only via the API). |
| `open_notebook/graphs/source.py` | A then B | A ☑ before B edits | A adds the structure/chaptering wiring; B adds the fire-and-forget verify+summary triggers. |
| `open_notebook/database/migrations/` + `async_migrate.py` | **A only** | — | All schema (the `source_section` table, `source.page_offset`, `source_embedding.section`, `cleaned_content`, `summary`) ships in **migration 17** in Chunk A1. B and C add **no** migrations. |
| `commands/` | A then B | A ☑ before B edits | A adds the backfill/chaptering command; B adds the verify-clean + summary commands (new files preferred to avoid churn). |

## Global status table
| Track | Chunk | Title | Status | Owner / session | Notes |
|-------|------:|-------|--------|-----------------|-------|
| A | A1 | Migration 17 + `SourceSection` model + page/section fields | ☐ todo | | foundation — unblocks everything |
| A | A2 | Docling extraction + page provenance (coordinate w/ pdf-viewer plan) | ☐ todo | | |
| A | A3 | Chaptering: structure node + section tree + `get_sections`/`get_outline` + section-tagged chunks + backfill | ☐ todo | | |
| B | B1 | Vision-verifier plumbing + **validation-gate pilot** | ☐ todo | | needs A ☑ |
| B | B2 | Per-chapter verify-clean background command (page-image ground truth) | ☐ todo | | |
| B | B3 | Per-section summaries + doc abstract (reuse transformation/insight engine) | ☐ todo | | |
| B | B4 | Tiered `get_context` rewrite (abstract + outline + retrieval, not raw `full_text`) | ☐ todo | | |
| B | B5 | Agent tools: `get_source_outline` / `get_section` | ☐ todo | | |
| C | C1 | `GET /sources/{id}/sections` + `SourceSectionResponse` + `has_sections` flag | ☐ todo | | needs A ☑ |
| C | C2 | Frontend types + API client (`getSections`) | ☐ todo | | |
| C | C3 | TOC sidebar + per-chapter rendering in `SourceDetailContent` | ☐ todo | | |
| C | C4 | Interaction layer: selection action menu + per-chapter AI actions + citation→jump-to-section | ☐ todo | | |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (cross-track)
- _(none yet — planning complete, awaiting execution.)_

## Context — why
Uploaded sources (esp. textbooks) are stored as one flat `full_text` blob — PyMuPDF flattens PDFs into a
wall of text. Two problems: **(1) unreadable** in the viewer (`SourceDetailContent.tsx` renders the whole
blob through one `ReactMarkdown`), and **(2) undigestible** by the chat agent — `Notebook.get_context`
(`notebook.py:69`) → `Source.get_context("long")` (`notebook.py:427`) dumps the **entire** `full_text` of
every source into the prompt. The fix is a **layered, multi-resolution document model**: an immutable raw
parse → a verified/cleaned layer → a chapter tree (`source_section`) → multi-resolution summaries → the
existing chunk embeddings — and to serve each consumer the right layer (human = TOC + per-chapter render;
agent = abstract + chapter-summary outline + on-demand retrieval, never the raw blob).

**North star (decided):** fidelity of the stored data + quality of viewing/interacting. **Cost and speed
are explicitly NOT constraints** — inference is local (DGX Spark), and a day-long background job is acceptable.

**Scope v1:** PDFs / long documents only. Other source types keep today's behavior.

## Decisions log (shared)
| # | Question | Decision |
|--:|----------|----------|
| 1 | What sources does v1 cover? | **PDFs / long documents only.** Web pages, pasted text, transcripts keep current behavior. |
| 2 | Cost / speed budget? | Not a constraint. Local inference (Spark), day-long background runs acceptable. Optimize for fidelity, not tokens. |
| 3 | Extraction engine? | **Docling** (structured markdown + per-block `page_no`/bbox); keep PyMuPDF as fallback. **Shared with `.claude/plans/pdf-viewer-citations.md` Phase 2** — adopt once; whichever plan lands it first owns the dependency, the other reuses. |
| 4 | New storage shape? | **`source_section` chapter-tree table** (additive). `full_text` stays as the **immutable raw parse** (never overwritten). Cleaned text + summaries are **separate derived layers** so they can be diffed/reverted. Summaries: per-section on `source_section.summary`; doc-level abstract as a `SourceInsight` (type `"abstract"`) — reuses the insight engine, no extra table. |
| 5 | Chapter-boundary detection? | PyMuPDF `doc.get_toc()` (PDF bookmarks) first; **Docling heading-hierarchy fallback**; headingless docs degrade to a single section (= today's behavior). |
| 6 | Verify-clean policy? | **Always run, full fidelity.** One chapter per agent session with context reset between chapters (parallelizable, resumable). Ground truth = rendered page images (PyMuPDF `get_pixmap`) fed alongside the parsed section markdown. |
| 7 | Verifier model? | **Qwen 3.6 Flash (multimodal/vision)** locally — confirmed multimodal in `.claude/plans/deepseek-v4-flash-ds4-integration.md:148-154`. **Validation gate (Chunk B1):** confirm the *deployed* Ollama build is the vision variant and pilot on a dense textbook page before trusting it. Fallback: cloud vision (Claude) for verify-only, or text-only dual-parse (PyMuPDF vs Docling) cross-check. |
| 8 | Page numbering? | **Physical page indices everywhere internally.** Printed labels are display/citation-only: auto-detect via PDF `PageLabels` → show detected anchor → user confirms/corrects a single body-start anchor → store `page_offset` per source. Manual anchor is a fallback/override, not mandatory per upload. |
| 9 | Chat context shape? | Tiered: default feeds title + doc abstract + chapter-summary **outline** + on-demand `vector_search` retrieval, **not** raw `full_text`. `/chat` endpoint contract unchanged — only what it feeds the model changes. |
| 10 | Viewer: cleaned vs raw text? | Viewer renders **cleaned per-section content by default**; raw `full_text` stays accessible (download + retained field). A raw/cleaned toggle is **deferred** to a later pass. |
| 11 | Annotations / PDF viewer / page-citation tokens? | **Deferred to `.claude/plans/pdf-viewer-citations.md`** (Phase 1 viewer, Phase 3 `[source:id#p=N]`, Phase 4 `source_annotation`). This plan does **not** build them — reuse that plan's model when it lands. |

### Reconciliation (input artifacts / sibling plans)
- **`.claude/plans/pdf-viewer-citations.md`** — overlaps on **Docling** (Chunk A2 ↔ its Phase 2: adopt once),
  and on page numbers (it does page-level citation tokens; we do internal physical indices + the display
  anchor). **Defer to it:** the inline PDF viewer, `[source:<id>#p=N]` citation tokens, and the
  `source_annotation` highlight/comment model. We own document *structuring* + *interaction surface*.
- **`.claude/plans/notebook-chat-workspace/` (ncw, LANDED)** — its selection/citation infra **already exists
  in code**: `PassageSelectionMenu.tsx` (selection → "Chat about this" sub-chat), `MessageReferences.tsx` +
  `Citation` type, and `ChatPanel.handleReferenceClick(type,id) → openModal` (`ChatPanel.tsx:160-171`).
  Chunk C4 **extends** these (selection action menu, citation→jump-to-section) — do **not** rebuild them.

## Conventions / translation notes (shared)
- **Migrations:** `N.surrealql` + `N_down.surrealql`; latest is **16**, so this plan's migration is **17**.
  `async_migrate.py` has a **hard-coded** `up_migrations` list (~98-127) and a down list (~174-176) — append
  migration 17 to both. `bump_version()` auto-increments; tables use `DEFINE … IF NOT EXISTS`. The `source`
  table is `SCHEMAFULL` so new fields need a `DEFINE FIELD`. (`source_embedding` is also SCHEMAFULL.)
- **Background jobs (surreal-commands):** `@command("name", app="open_notebook", retry={...})` on an
  `async def fn(input_data: XInput) -> XOutput` (Pydantic `CommandInput`/`CommandOutput`); submit fire-and-forget
  with `submit_command("open_notebook", "name", {...})` → returns `command_id`. Worker:
  `surreal-commands-worker --import-modules commands` (`Makefile:145`). Pattern refs: `create_insight_command`
  (`commands/embedding_commands.py:738-820`), `process_source_command` (`commands/source_commands.py:49-113`).
- **Models:** `provision_langchain_model(content, model_id, default_type, **kwargs)` (`ai/provision.py:10-61`,
  auto-upgrades to `large_context` >105k tokens). `DefaultModels` slots in `ai/models.py:62-95`
  (`default_vision_model` is **commented out** — B1 adds it). Vision input reuses
  `graphs/chat.py:_attach_media_blocks` (70-105), which inlines images as data-URIs onto a `HumanMessage`.
- **i18n:** every new frontend label needs locale keys across `frontend/src/lib/locales/*` (append-only).
- **Frontend markdown:** reuse the existing `ReactMarkdown` + `remarkGfm` + custom components block in
  `SourceDetailContent.tsx:523-548`; do not introduce a second renderer.

## Reference index (shared)
- **Ingest graph:** `open_notebook/graphs/source.py` — `SourceState` (19-26); nodes `content_process` (34-107,
  `output_format="markdown"` @60, `extract_content` @78), `save_source` (110-140, writes `full_text` @120,
  `vectorize()` @134), `transform_content` (162-181), `trigger_transformations` conditional (143-159); wiring 185-200.
- **Domain:** `open_notebook/domain/notebook.py` — `Source` (354-620), `SourceInsight` (323-351), `SourceEmbedding`
  (304-320), `Source.add_insight` (525-570), `Notebook.get_context` (69-127), `Source.get_context` (427-440),
  `vector_search` (744-774), `text_search` (702-741). Context assembler: `open_notebook/utils/context_builder.py`
  (callers @170, @280).
- **Transformations:** `graphs/transformation.py` `run_transformation` (23-68) renders Jinja → provisions
  `"transformation"` model → `source.add_insight(transformation.title, cleaned)`.
- **Chunking/embeddings:** `utils/chunking.py` `chunk_text(text, content_type, file_path)` (419-494);
  `commands/embedding_commands.py` `embed_source` (365-501) bulk-inserts `source_embedding` rows.
- **Agent tools:** `open_notebook/ai/claude_agent_tools.py` — `@tool(name, desc, schema)` + `create_sdk_mcp_server`
  (existing: `list_notebooks/get_notebook/list_sources/get_source/get_note/search`).
- **API:** `api/routers/sources.py` `GET /sources/{id}` (572-632); `api/models.py` `SourceResponse` (359-376),
  `SourceListResponse` (378-393), `AssetModel` (302-304); routers registered `api/main.py:303`.
- **Frontend:** `frontend/src/components/source/SourceDetailContent.tsx` tabs (466-551), markdown render (523-548,
  `full_text` @546); page `frontend/src/app/(dashboard)/sources/[id]/page.tsx` (27-76, grid `2fr/1fr`);
  types `frontend/src/lib/types/api.ts` (21-46); client `frontend/src/lib/api/sources.ts`.
  Reuse-on-extend: `PassageSelectionMenu.tsx`, `MessageReferences.tsx`, `ChatPanel.handleReferenceClick` (160-171).

### Post-exploration refinements (confirmed APIs)
- `Source.get_context` returns a **dict**; callers do `.get("full_text")`/`.get("insights")` — B4 must keep
  `id`/`title`/`insights` keys and add `abstract`/`outline`, updating `context_builder.py` to consume them.
- No Esperanto **vision factory** exists; the working path is "provision a vision-capable chat model + attach
  media blocks" (B1). Validate Esperanto+Ollama actually forwards `image_url` blocks during the B1 pilot.
- ncw selection/citation components are **already merged** — C4 extends, never rebuilds.

## Open Questions (cross-track — see also each track's own list)
- **Q-docling-install** — Docling on aarch64 + CUDA (Spark): wheel availability, model-weights download/license,
  Docker pre-bake. *Default:* A2 adds it behind the existing `document_engine` config with PyMuPDF fallback;
  if pdf-viewer-citations already landed Docling, reuse that and make A2 a no-op verification.
- **Q-qwen-vision** — Is the *deployed* Ollama Qwen the vision build, and does Esperanto+Ollama forward image
  blocks? **Validation gate in B1** (pilot on a dense page). *Fallback:* cloud vision (Claude) for verify-only,
  or text-only dual-parse cross-check.

## Completion & archival
The track that marks the **last** chunk ☑ (sees every track complete in the Global status table) appends a
final Changelog line and moves the **whole feature directory** to `.claude/plans/archived/source-chaptering/`
(`mkdir -p .claude/plans/archived && mv .claude/plans/source-chaptering .claude/plans/archived/`), then tells
the user the plan is complete and archived.