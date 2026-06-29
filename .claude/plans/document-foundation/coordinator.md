# Document Foundation — Coordinator / Index

> **Canonical location:** `.claude/plans/document-foundation/coordinator.md`
> **Type:** Multi-track coordinator. This file is the shared source of truth — decisions,
> conventions, shared-file ownership, concurrency matrix, global status table, and reference index.
> Each **track file** is self-contained for one chat; a track chat reads THIS file first, then owns
> exactly one track file. Do not re-read this file mid-execution unless looking up a decision.
>
> **Supersedes:**
> - `.claude/plans/source-chaptering/` (archived 2026-06-26)
> - `.claude/plans/pdf-viewer-citations.md` (archived 2026-06-26)

---

## SESSION HANDOFF (read first)

**State (2026-06-26):** Plan authored. No chunks started. Background-jobs A1 is committed (the
`chat_commands.py` / `_heavy_lane.py` WAL-pragma work). Migration 17 = chat_tag_colors on notebooks
(landed). Migration 18 = reserved for chat-foundation B1. This plan uses **migration 19** (A1)
and **migration 20** (Phase3). Migration 21 is reserved for Phase4 (deferred).

**Orchestrator prompt (paste to drive a wave from the meta-coordinator):**
```
Read .claude/plans/cross-plan-orchestration/coordinator.md then
.claude/plans/document-foundation/coordinator.md. Determine which document-foundation chunk is
runnable next from the Global status table cross-checked against `git log --oneline -30`. For each
runnable chunk print: (a) the track to run, (b) the paste-able resume prompt from that track's
SESSION HANDOFF block, (c) the model, (d) the verify command. Do NOT implement here.
```

---

## How to run a track in a fresh chat

Pick a track whose deps are ☑ in the Global status table, open its file in a **fresh chat**, and
paste its SESSION HANDOFF resume prompt. That prompt is self-locating (derives the next unstarted
chunk from the Status table + `git log`). One chunk per session; announce ✅ when done.

**Standalone phases (Phase1, Phase3)** use `standalone.md` — each has its own resume prompt.

### Per-track resume prompts (copy from here)

**Track A — Foundation** (`a-foundation.md`, no deps, head of critical path):
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/a-foundation.md in full. Implement the next unstarted chunk (one
only, derive from the Status table + `git log --oneline -30`). Verify (API restart → migration
logs + pytest tests/test_domain.py for A1; Spark GPU spot-check for A2; pytest tests/ + section
tree for A3). Commit (one chunk = one commit). Update BOTH the track Status table AND the
coordinator Global status table + Changelog. Announce ✅ Chunk A.n complete — safe to clear context.
Then stop.
```

**Track B — Backend pipeline** (`b-pipeline.md`, **needs A ☑**):
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/b-pipeline.md in full. Confirm Track A is fully ☑ in the
coordinator before starting. Implement the next unstarted chunk (one only). ⚠ B1 is a HUMAN GATE —
stop after the pilot and report GO/NO-GO before continuing to B2. Verify per the chunk spec. Commit.
Update BOTH status tables + Changelog. Announce ✅ Chunk B.n complete — safe to clear context. Stop.
```

**Track C — Surfaces** (`c-surfaces.md`, **needs A ☑**, concurrent with B):
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/c-surfaces.md in full. Confirm Track A is fully ☑ in the
coordinator before starting. Implement the next unstarted chunk (one only). Verify: uv run pytest
tests/test_models_api.py (backend); npm run build (frontend). Commit. Update BOTH status tables +
Changelog. Announce ✅ Chunk C.n complete — safe to clear context. Stop.
```

**Phase1 — PDF Viewer** (`standalone.md`, **no deps**, independent):
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/standalone.md — Phase1 section only. Implement Phase1 (PDFViewer
component + tab integration). Verify: npm run build passes; PDF renders in browser for a real source
with file_available=true. Commit. Update BOTH the standalone Status table AND the coordinator Global
status table + Changelog. Announce ✅ Phase1 complete — safe to clear context. Stop.
```

**Phase3 — Page citations** (`standalone.md`, **needs A2 ☑** and ideally **Phase1 ☑**):
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/standalone.md — Phase3 section only. Confirm A2 is ☑ and Phase1
is ☑ in coordinator before starting (Phase1 needed for the citation-click→PDF-open flow). Implement
Phase3 (migration 20 + provenance-aware chunking + citation tokens + FE ref parser). Verify: API
restart → migration 20 applied; re-embed a PDF → source_embedding rows carry page_number; citation
[source:id#p=3] in chat scrolls PDFViewer to page 3. Commit. Update BOTH status tables + Changelog.
Announce ✅ Phase3 complete — safe to clear context. Stop.
```

---

## Concurrency matrix

| Track | File | Depends on (must be ☑) | Concurrent with | Why |
|-------|------|------------------------|-----------------|-----|
| A — Foundation | `a-foundation.md` | — | Phase1 | Head of critical path |
| B — Backend pipeline | `b-pipeline.md` | **A** | **C**, Phase3 | Extends notebook.py/source.py/commands/ai that A created |
| C — Surfaces | `c-surfaces.md` | **A** | **B**, Phase3 | Touches only api/* + frontend/* — disjoint from B |
| Phase1 — PDF viewer | `standalone.md` (Phase1) | — | A, B, C | FE-only, no migration, no backend |
| Phase3 — Citations | `standalone.md` (Phase3) | **A2** (+ Phase1 recommended) | B, C tail | Needs page_map from A2; FE citation→PDF click needs Phase1 |
| Phase4 — Annotations | `standalone.md` (Phase4) | Phase1, Phase3 | — | **DEFERRED** — do not schedule until P1+P3 ☑ |

> **A first, alone.** Then **B ‖ C** (and Phase1 can run at any time; Phase3 after A2).
> B and C share **no files** — B touches backend domain/graphs/commands/ai; C touches api/models.py
> + api/routers/sources/ + frontend/. They are safe to run simultaneously once A is ☑.

---

## Shared-file ownership (cross-track conflict map)

| File | Primary owner | Secondary (must wait for) | Rule |
|------|--------------|--------------------------|------|
| `open_notebook/domain/notebook.py` | **A** (SourceSection model, get_sections/get_outline, page_offset) | **B** (get_context, summarize+cleaned helpers) | B starts ONLY after A☑. C must NOT touch it. |
| `open_notebook/database/async_migrate.py` | **A1** (appends mig 19 to both lists) | **Phase3** (appends mig 20) | Phase3 appends ONLY after A1☑. One editor at a time. |
| `open_notebook/utils/chunking.py` | **A3** (section-aware chunk tagging) | **Phase3** (page_number provenance) | Phase3 edits ONLY after A3☑. |
| `commands/embedding_commands.py` | **A3** (stamp section on source_embedding) | **Phase3** (stamp page_number on source_embedding) | Phase3 edits ONLY after A3☑. |
| `open_notebook/graphs/source.py` | **A** (structure node + wiring) then **B2** (fire-and-forget triggers) | — | B2 edits ONLY after A☑. C must NOT touch it. |
| `frontend/src/components/source/detail/SourceDetailContent.tsx` | **Phase1** (add PDF tab/toggle) | *(C3 touches SourceContentTab.tsx, not this file)* | Phase1 edits the tab wrapper; C3 edits the content tab body. No conflict if Phase1 lands first. |

> **Intra-track ordering** (A1→A2→A3; B1→…→B5; C1→…→C4) is enforced by each track's own sequential structure — trust the track files.

---

## Global status table (executor updates this after each chunk)

Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred

| Track | Chunk | Title | Status | Notes |
|-------|------:|-------|--------|-------|
| A | A1 | Migration 19 + SourceSection model + page/section fields | ☑ | commit 34ec0bd; mig19 schema LIVE in DB (source_section + page_offset/page_labels + source_embedding.section). wave1 2026-06-29 |
| A | A2 | Docling extraction + page provenance (folds pdf Phase 2) | ☐ | Verify on Spark (GPU) |
| A | A3 | Chaptering: section tree + get_sections/get_outline + tagged chunks + backfill | ☐ | |
| B | B1 🚧 | Vision-verifier plumbing + **validation-gate pilot** | ☐ | **HUMAN GATE** — needs A ☑; GO/NO-GO before B2 |
| B | B2 | Per-chapter verify-clean background command | ☐ | Needs B1 GO |
| B | B3 | Per-section summaries + doc abstract | ☐ | |
| B | B4 | Tiered get_context rewrite | ☐ | The digestion fix |
| B | B5 | Agent tools get_source_outline / get_section | ☐ | |
| C | C1 | GET /sources/{id}/sections + schemas + has_sections flag | ☐ | Needs A ☑; sources.py is a package |
| C | C2 | Frontend types + getSections API client | ☐ | |
| C | C3 | TOC sidebar + per-chapter rendering (SourceContentTab) | ☐ | Anchors in SourceContentTab.tsx |
| C | C4 | Interaction: selection actions + per-chapter AI + citation→jump | ☐ | |
| — | Phase1 | PDFViewer.tsx inline viewer (FE-only, dep-free) | ☐ | Independent — any time |
| — | Phase3 | page_number/bbox + vector_search + #p=N citations (mig 20) | ☐ | Needs A2 ☑ + Phase1 ☑ |
| — | Phase4 | Annotations (source_annotation, mig 21, highlight plugin) | ⊘ | **DEFERRED** — do not start until Phase1+Phase3 ☑ |

---

## Context — why

Uploaded sources (esp. textbooks) are stored as one flat `full_text` blob. Two problems:

1. **Unreadable in the viewer.** `SourceContentTab.tsx` renders the whole blob through one `ReactMarkdown` instance — a wall of text for a 400-page textbook.
2. **Undigestible by the chat agent.** `Notebook.get_context` → `Source.get_context("long")` dumps the **entire** `full_text` of every source into the LLM prompt. A textbook hits 200k+ tokens; context windows fill before any reasoning.

The fix is a **layered, multi-resolution document model**:

```
raw parse (full_text, immutable)
  └─ Docling extraction → structured markdown + per-block (text, page_no)
       ├─ section tree (source_section) — chapter boundaries, page ranges
       │    ├─ verified/cleaned layer (cleaned_content) — vision-verifier corrects parser artifacts
       │    └─ per-section summaries + doc abstract
       ├─ page-level embedding (page_number on source_embedding) → #p=N citation tokens
       └─ inline PDF viewer (Phase1) + citation-jump (Phase3) + annotations (Phase4, deferred)
```

Chat agent gets: title + abstract + chapter outline (summaries) + on-demand retrieval — never the raw blob.
Human viewer gets: TOC + per-chapter render (cleaned content) + inline PDF + citation jumps.

**North star (decided):** fidelity and viewing quality. Cost and speed are NOT constraints — inference is local (DGX Spark, GPU), and a day-long background job is acceptable.

---

## Decisions log

| # | Question | Decision |
|--:|----------|----------|
| 1 | Extraction engine? | **Docling** (MIT, structured markdown + per-block page_no/bbox). PyMuPDF (fitz) as fallback — already a transitive dep. |
| 2 | Viewer lib? | **@react-pdf-viewer** (MIT, has highlight plugin for Phase4). Fallback: react-pdf + custom highlight layer if React 19 / Next 16 peer-dep issues. Configure PDF.js worker for Next 16. |
| 3 | Citation token? | **[source:\<id\>#p=\<n\>]** — extends existing [source:id] format; old citations keep working. |
| 4 | Chapter boundary detection? | PyMuPDF `doc.get_toc()` (PDF bookmarks) first → Docling heading-hierarchy fallback → single section spanning whole doc if neither. |
| 5 | Cleaned vs raw text? | `full_text` is the **immutable raw parse** — never overwritten. Cleaned text lives in `source_section.cleaned_content` (a derived layer, diffable/revertable). |
| 6 | Vision model? | `default_vision_model` → deployed Ollama **Qwen 3.6** (confirm it's the vision build in B1 gate). Fallback: cloud vision (Claude) for verify-only, or text-only dual-parse cross-check. |
| 7 | Chat context? | **Tiered:** title + doc abstract + chapter-summary outline + on-demand `vector_search` retrieval. Never raw `full_text`. |
| 8 | Page numbering? | **Physical page indices** everywhere internally. Printed labels = display/citation-only. Auto-detect via PDF `PageLabels`; store as `page_offset` per source (null = identity). |
| 9 | Viewer content default? | Viewer renders **cleaned per-section content** (when present); raw always accessible via the existing download endpoint. No raw/cleaned toggle in v1. |
| 10 | Annotations scope? | **Deferred to Phase4.** Phase3 establishes bbox coords; Phase4 uses them for highlight/comment anchoring. |
| 11 | Migrations? | 17 = taken (chat_tag_colors). 18 = reserved for chat-foundation B1. **19** = this plan's A1 (source_section + all additive source fields). **20** = Phase3 (page_number/bbox on source_embedding). 21 = Phase4 source_annotation (deferred). |
| 12 | Which sources? | **PDFs / long documents only** in v1. Web pages, pasted text, transcripts keep current behavior. |
| 13 | Viewer lib peer-dep risk? | Validate @react-pdf-viewer in Phase1. If React 19/Next 16 peer-dep fails, fall back to react-pdf + a custom highlight layer. Do NOT block B or C on this — Phase1 is independent. |

---

## Conventions (shared across all tracks)

### Migrations
- Files: `open_notebook/database/migrations/N.surrealql` + `N_down.surrealql`.
- Latest committed = **17**. Chat-foundation reserves **18**. This plan uses **19** (A1) and **20** (Phase3).
- `async_migrate.py` has a **hard-coded** `up_migrations` list (lines ~98–128) and a down list (~174–181). Append migration N to **both lists**. `bump_version()` auto-increments.
- `source` and `source_embedding` tables are **SCHEMAFULL** → new fields need `DEFINE FIELD IF NOT EXISTS`.
- `DEFINE TABLE IF NOT EXISTS source_section SCHEMAFULL` for the new table.
- Down migrations: `REMOVE TABLE source_section;` + `REMOVE FIELD … ON TABLE source;`.

### Background jobs
- Decorator: `@command("name", app="open_notebook", retry={"max_retries": N, "delay_seconds": D})`.
- Function signature: `async def fn(input_data: XInput) -> XOutput` where `XInput(CommandInput)` and `XOutput(CommandOutput)` are Pydantic models.
- Submit fire-and-forget: `submit_command("open_notebook", "name", {...})` → returns `command_id`.
- Pattern refs: `create_insight_command` (`commands/embedding_commands.py:738–820`), `process_source_command` (`commands/source_commands.py:49–113`).

### Models / AI provisioning
- `provision_langchain_model(content, model_id, default_type, **kwargs)` — auto-upgrades to `large_context` >105k tokens.
- `DefaultModels` slots in `ai/models.py:62–95`. `default_vision_model` is **commented out** — B1 adds it.
- No Esperanto vision factory exists. Working path: provision a vision-capable chat model + attach image blocks via `_attach_media_blocks` from `graphs/chat.py:70–105`.

### Frontend
- **i18n:** every new label → locale keys across `frontend/src/lib/locales/*/` (append-only).
- **ReactMarkdown:** reuse the existing `ReactMarkdown + remarkGfm + custom components` block in `SourceContentTab.tsx:87–110`. Do NOT introduce a second renderer.
- **Verify:** `npm run build` (full compile) + visual spot-check for content-rendering changes.
- **Post-refactor paths:** `api/routers/sources/` (package); `SourceDetailContent.tsx` → `frontend/src/components/source/detail/`; `SourceContentTab.tsx` → same directory; `useSourceDetail` → `frontend/src/lib/hooks/useSourceDetail.ts`; `PassageSelectionMenu.tsx` → `frontend/src/components/notebooks/workspace/`; `ChatPanel.tsx` → `frontend/src/components/source/chat/`.

### SurrealDB domain model pattern
- New model: `class SourceSection(ObjectModel)` with `table_name = "source_section"` and all option<> fields listed in `nullable_fields`.
- Ref: `SourceInsight` (323–351) and `SourceEmbedding` (304–320) in `notebook.py` as shape templates.

---

## Reference index

### Backend
| Symbol | File | Lines | Notes |
|--------|------|-------|-------|
| `content_process` node | `open_notebook/graphs/source.py` | 34–107 | PDF extraction entry; `output_format="markdown"` @60; `extract_content` @78 |
| `save_source` node | `open_notebook/graphs/source.py` | 110–140 | writes `full_text` @120, calls `vectorize()` @134 |
| Graph wiring | `open_notebook/graphs/source.py` | 185–200 | where to add the `structure` node after `save_source` |
| `Source` | `open_notebook/domain/notebook.py` | 354–620 | main domain model |
| `SourceInsight` | `open_notebook/domain/notebook.py` | 323–351 | model template for new SourceSection |
| `SourceEmbedding` | `open_notebook/domain/notebook.py` | 304–320 | model template |
| `Source.add_insight` | `open_notebook/domain/notebook.py` | 525–570 | used by B3 for abstract |
| `Notebook.get_context` | `open_notebook/domain/notebook.py` | 69–127 | B4 rewrites this |
| `Source.get_context` | `open_notebook/domain/notebook.py` | 427–440 | B4 changes "long" return value |
| `vector_search` | `open_notebook/domain/notebook.py` | 744–774 | Phase3 updates to return page_number |
| `text_search` | `open_notebook/domain/notebook.py` | 702–741 | |
| `chunk_text` | `open_notebook/utils/chunking.py` | 419–494 | A3 stamps section; Phase3 stamps page_number |
| `embed_source` | `commands/embedding_commands.py` | 365–501 | A3 stamps section; Phase3 stamps page_number |
| `create_insight_command` | `commands/embedding_commands.py` | 738–820 | background command template |
| `process_source_command` | `commands/source_commands.py` | 49–113 | command template |
| `DefaultModels` | `open_notebook/ai/models.py` | 62–95 | B1 adds `default_vision_model` |
| `provision_langchain_model` | `open_notebook/ai/provision.py` | 10–61 | |
| `_attach_media_blocks` | `open_notebook/graphs/chat.py` | 70–105 | B1 reuses for vision |
| `run_transformation` | `open_notebook/graphs/transformation.py` | 23–68 | B3 reuses for summaries |
| `@tool` + `create_sdk_mcp_server` | `open_notebook/ai/claude_agent_tools.py` | full file | B5 adds two tools |
| `context_builder` | `open_notebook/utils/context_builder.py` | 170, 280 | B4 updates callers |
| `fn::vector_search` SurrealQL | `open_notebook/database/migrations/4.surrealql` | 75–133 | Phase3 updates to return page_number + bbox |
| `SourceResponse` / `AssetModel` | `api/models.py` | 359–376, 302–304 | C1 adds has_sections/sections_count |
| Sources router | `api/routers/sources/` | package | C1 adds `sections.py` + wires in `__init__.py` |

### Frontend
| Symbol | File | Notes |
|--------|------|-------|
| `SourceDetailContent` | `frontend/src/components/source/detail/SourceDetailContent.tsx` | Tab wrapper (tabs 1–N); Phase1 adds PDF tab |
| `SourceContentTab` | `frontend/src/components/source/detail/SourceContentTab.tsx` | ReactMarkdown render @87–110; C3 adds TOC |
| `useSourceDetail` hook | `frontend/src/lib/hooks/useSourceDetail.ts` | data fetching for source detail |
| Source page layout | `frontend/src/app/(dashboard)/sources/[id]/page.tsx` | 27–76 |
| `SourceDetailResponse` types | `frontend/src/lib/types/api.ts` | 21–46; C2 adds section types |
| Sources API client | `frontend/src/lib/api/sources.ts` | C2 adds getSections; Phase1 uses downloadFile |
| `PassageSelectionMenu` | `frontend/src/components/notebooks/workspace/PassageSelectionMenu.tsx` | LANDED — C4 extends |
| `MessageReferences` | `frontend/src/components/source/chat/MessageReferences.tsx` | LANDED — citation display |
| `ChatPanel.handleReferenceClick` | `frontend/src/components/source/chat/ChatPanel.tsx` | 126 — openModal; C4 extends |
| `source-references.tsx` | `frontend/src/lib/utils/source-references.tsx` | Phase3 extends to parse #p=N |

---

## Completion & archival

The track/phase that marks the **last build-now chunk ☑** (sees every non-deferred row ☑ in the
Global status table) appends a final Changelog line and moves the **whole directory**:
```
mkdir -p .claude/plans/archived
mv .claude/plans/document-foundation .claude/plans/archived/document-foundation
```
Phase4 (⊘ deferred) does NOT block archival — archive when A1–A3, B1–B5, C1–C4, Phase1, Phase3 are all ☑.

Also archive the two superseded plans if not already done:
```
mv .claude/plans/source-chaptering .claude/plans/archived/source-chaptering
# pdf-viewer-citations.md → archived/ as a single file
mv .claude/plans/pdf-viewer-citations.md .claude/plans/archived/pdf-viewer-citations.md
```

---

## Open Questions (cross-track)

- **Q-docling-install** — Docling on aarch64 + CUDA (Spark): wheel availability, model-weights download, Docker pre-bake, license check. *Default:* A2 adds it behind `document_engine` config with PyMuPDF fallback; if `content-core`'s Docling wrapper exposes `page_no`, prefer that over calling Docling directly. Resolve in A2.
- **Q-qwen-vision** — Is the deployed Ollama Qwen the vision build? Does Esperanto+Ollama forward image_url blocks? *Default:* B1 pilot answers this. If NO: fall back to cloud vision (Claude) for verify-only or text-only dual-parse cross-check; adjust B2 design accordingly.
- **Q-section-content-payload** — Return `content` inline in the sections endpoint or lazy per-section fetch? *Default:* `summary` always inline; `content` only on demand (keep tree payload light). Revisit if UX needs it.
- **Q-viewer-peer-dep** — @react-pdf-viewer React 19/Next 16 compatibility. *Default:* Phase1 validates; fallback to react-pdf + custom highlight layer. Resolve in Phase1.

---

## Changelog

- 2026-06-26 — Document-foundation plan authored. Supersedes source-chaptering/ and
  pdf-viewer-citations.md. Migration 19 for Track A, 20 for Phase3. Post-refactor paths confirmed
  (sources.py → package; SourceDetailContent → detail/; SourceContentTab owns ReactMarkdown render;
  PassageSelectionMenu in notebooks/workspace/). Wave 0 / P3 ☑ in meta-coordinator.
