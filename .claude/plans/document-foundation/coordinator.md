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

**State (2026-07-02, wave5d — ALL CODE LANDED):** Track A ☑. **Track C ☑ (C1–C4).** Phase1 ☑.
Track B: B1 ☑; **B2, B3, B4, B5 all ◐** (code integrated + green; live/decision items parked). **Phase3 ◐.**
Every build-now chunk's CODE is written, integrated on `feature/multipanelchat`, and static-verified
(backend full suite 214 pass; frontend tsc baseline-only). **Document-foundation is NOT archived** — the
◐ chunks await the end-of-run PUNCH-LIST:
  • **Decision #21 🚧 (X-nonpdf-longcontext)** — B4 non-PDF fallback (recommended fix in Decisions log).
  • **Decision #20 (Q-citation-pdf-open)** — citation→PDF-page-open follow-up chunk.
  • **LIVE spot-checks** (need running services + a real PDF): Phase3 migration-apply (watch fn::vector_search
    redefine) + re-embed→page_number; B2 verify-clean on a real section; B3 summaries/abstract; B4 no-balloon
    chat; B5 agent tool-calls; C3/C4 visual; D1 toast render.
Once the decisions are answered + the live checks pass, flip the ◐ chunks to ☑ and archive the directory.

> **Update (2026-07-02, post-fix):** Decision #21 (B4 non-PDF fallback) **✅ RESOLVED** in-run (commit
> 8c0b606, tested). The only remaining *decision* on the punch-list is **#20 (citation→PDF-page-open
> follow-up)**; everything else is a **live spot-check** needing running services + a real PDF.

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
| `open_notebook/graphs/source.py` | **A** (structure node + wiring) then **B2** (fire-and-forget triggers) | **Phase3** (persist `page_map` in save_source — added 2026-07-02) | B2 edits ONLY after A☑. **B2 and Phase3 NEVER in the same wave** — whichever runs first completes before the other starts. C must NOT touch it. |
| `open_notebook/domain/notebook.py` (see also row 1) | **A** then **B** | **Phase3** (adds `Source.page_map` field) | Phase3's model edit must not run concurrently with any B chunk (B owns this file after A). Serialize: Phase3 ↔ B, either order. |
| `frontend/src/components/source/detail/SourceDetailContent.tsx` | **Phase1** (add PDF tab/toggle) | *(C3 touches SourceContentTab.tsx, not this file)* | Phase1 edits the tab wrapper; C3 edits the content tab body. No conflict if Phase1 lands first. |

> **Intra-track ordering** (A1→A2→A3; B1→…→B5; C1→…→C4) is enforced by each track's own sequential structure — trust the track files.

---

## Global status table (executor updates this after each chunk)

Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred

| Track | Chunk | Title | Status | Notes |
|-------|------:|-------|--------|-------|
| A | A1 | Migration 19 + SourceSection model + page/section fields | ☑ | commit 34ec0bd; mig19 schema LIVE in DB (source_section + page_offset/page_labels + source_embedding.section). wave1 2026-06-29 |
| A | A2 | Docling extraction + page provenance (folds pdf Phase 2) | ☑ | commit 7e13d72; content-core[docling] dep + page_map provenance + PyMuPDF fallback. wave2 2026-06-29. ⚠ GPU spot-check on real textbook still pending (manual) |
| A | A3 | Chaptering: section tree + get_sections/get_outline + tagged chunks + backfill | ☑ | commit 6ba9f40; build_sections+backfill_sections commands, section tree + get_sections/get_outline, chunk→section stamping, graph rewire. pytest 31 pass; worker 16 cmds; api clean. ⚠ live-ingest spot-check pending. **Track A fully ☑ → B & C unblocked; Phase3 unblocked.** wave3 2026-06-29 |
| B | B1 🚧 | Vision-verifier plumbing + **validation-gate pilot** | ☑ | commit 87de266 (wave4 2026-07-02). Real pilot run — **GO-WITH-CAVEATS, human-blessed 2026-07-02.** Gate-bypass credential fixed same session |
| B | B2 | Per-chapter verify-clean background command | ◐ | commit 09c0fed (wave5b 2026-07-02); `verify_clean_section`+`verify_clean_source` cmds, PyMuPDF 2× render, cleaned→`cleaned_content` (raw immutable), discrepancies→`verify_flag` insight, fire-and-forget trigger in `submit_sections`. Static verify green (imports+register, pytest 31). **LIVE spot-check parked:** run on a real section → cleaned better + raw byte-unchanged + verify_flag + fan-out + failure isolation; math path untested. Auto-decisions: direct `get_vision_model(max_tokens=8192)` (NOT `provision_langchain_model` — avoids >105k non-vision large-context swap); retry schema→`max_attempts=3/fixed 10s/stop_on ValueError,ConfigError`; `_MAX_VERIFY_PAGES=50` skip-with-flag |
| B | B3 | Per-section summaries + doc abstract | ◐ | commit abb9444 (wave5c 2026-07-02); `summarize_section`+`generate_source_abstract` (commands/summary_commands.py), `Source.summarize_sections()` fan-out, trigger after B2's verify in `submit_sections`. Static verify green (register, **full suite 214 pass**). **LIVE spot-check parked:** real run → summaries non-null <500w, `abstract` insight, get_outline surfaces summaries, idempotent re-run. Auto-decisions #17–19 |
| B | B4 | Tiered get_context rewrite | ◐ | commit c6f6004 (wave5d 2026-07-02); `Source.get_context("long")` → {id,title,insights,abstract,outline} (no full_text); `format_source_long_context` renders Abstract + flattened Chapters; `Notebook.get_context` rewired; short unchanged (no "medium" tier exists). Integrated + **full suite 215 pass**. Decision #21 (non-PDF fallback) **✅ RESOLVED** by orchestrator fix 8c0b606 (implements Decision #12 + regression test). Only the **LIVE no-balloon spot-check** remains parked |
| B | B5 | Agent tools get_source_outline / get_section | ◐ | commit 1effece (wave5d 2026-07-02); `get_source_outline`+`get_section` @tool (conformed to file's real dict-arg/`_result` pattern, not the plan's illustrative shape), registered in MCP server; `get_source` kept full_text + added nav hints; `get_section` content capped at 4000 chars. **full suite 214 pass, ruff clean, MCP builds.** **LIVE spot-check parked** (agent actually calls the tools + answers a chapter question). Minor: confirm the 4000-char section cap |
| C | C1 | GET /sources/{id}/sections + schemas + has_sections flag | ☑ | commit c498aa4 (wave4 2026-07-02); recovered from a prior session's unmerged worktree (orig 67c3b7d) — implementation complete and verified, just never integrated. `pytest tests/test_models_api.py` 12 passed |
| C | C2 | Frontend types + getSections API client | ☑ | commit 22eca7c (wave5 2026-07-02); SourceSectionNode/SourceSectionResponse types + has_sections?/sections_count? on SourceDetailResponse + getSections client. tsc clean (baseline only). ⚠ `title` typed non-optional per verbatim spec; backend `title` is nullable — C3 should tolerate null |
| C | C3 | TOC sidebar + per-chapter rendering (SourceContentTab) | ☑ | commit 887bf95 (wave5b 2026-07-02); `SourceTOC.tsx` (sticky collapsible tree, `data-section-id` anchors) + two-col `SourceContentTab` reusing the existing ReactMarkdown; content via `getSections(id,true)`; unchaptered fallback preserved; null-title tolerated; 3 locale keys ×14. tsc clean (baseline only). ⚠ visual spot-check parked (TOC renders for chaptered PDF; flat render for web/pasted). Exposes `getSectionPageRangeLabel` + anchors for C4 |
| C | C4 | Interaction: selection actions + per-chapter AI + citation→jump | ☑ | commit a530bfa (wave5c 2026-07-02); PassageSelectionMenu Explain+Save-note, SourceTOC per-chapter Summarize/Quiz (onSectionAction prop-down, Q-c4-chat-scope resolved), ChatPanel citation→section-anchor scroll, 5 keys ×14. tsc clean; reuse confirmed; no annotations (Phase4 OUT). **Track C fully ☑.** ⚠ visual spot-checks parked. ⚠ **citation→PDF-page-open last mile = follow-up** (needs SourceDetailContent controlled tabs + PDFViewer initialPage — outside C4's files; Q-citation-pdf-open). Section-anchor scroll dormant until citations carry section ids |
| — | Phase1 | PDFViewer.tsx inline viewer (FE-only, dep-free) | ☑ | commit 1608053; @react-pdf-viewer + PDFViewer.tsx + Original PDF tab + 14 locales + next.config worker. wave2 2026-06-29. ⚠ browser render spot-check still pending (manual) |
| — | Phase3 | page_number/bbox + vector_search + #p=N citations (mig 20) | ◐ | commit b525c88 (wave5 2026-07-02); mig20 (page_map/page_number/bbox + fn::vector_search REMOVE+DEFINE redefine) + provenance chunking (build_page_char_map/find_chunk_page) + embed_source page_number stamping + backfill_page_numbers cmd + #p=N parser (forwards `page` arg to C4). Static verify green (pytest 65 + test_chunking 34, imports OK, mig20 in both lists). **LIVE spot-checks PARKED:** (1) migration-apply on API restart — WATCH the fn::vector_search redefine for SurrealQL errors; (2) re-embed PDF → page_number; (3) chat emits #p=N; (4) citation→PDF-open (final wiring is C4's — parser already forwards page); (5) npm build |
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
| 14 | B2 vision provisioning path? | **auto-decided (B2, 2026-07-02):** call `get_vision_model(max_tokens=8192).to_langchain()` **directly**, NOT `provision_langchain_model(...)` — the latter auto-upgrades >105k-token content to a non-vision `large_context_model` → garbage on large sections. Direct path also returns None cleanly when unconfigured (the required skip path). **Confirm if you'd prefer routing through provision.** |
| 15 | B2 retry config? | **auto-decided (B2):** the plan's `{max_retries, delay_seconds}` fields don't exist in the installed `surreal_commands.RetryConfig` (silently ignored). Translated to `{max_attempts:3, wait_strategy:"fixed", wait_time:10, stop_on:[ValueError, ConfigurationError]}` = 1 initial + 2 retries, fixed 10s. Verified against the library. |
| 16 | B2 pathological page span? | **auto-decided (B2):** a headingless PDF chapters into one whole-doc section → rendering hundreds of page-images into one vision call blows context. `_MAX_VERIFY_PAGES=50`: over the cap → **skip-with-`verify_flag`** (never truncate — truncation violates "preserve all content"). **Confirm the cap value (50).** |
| 17 | B3 abstract idempotency? | **auto-decided (B3):** `add_insight` always CREATEs, so `generate_source_abstract` first queries `get_insights()`, synchronously `.delete()`s any existing `insight_type=="abstract"` row, then re-adds — re-runs replace rather than duplicate. |
| 18 | B3 abstract readiness gate? | **auto-decided (B3):** deviates from the verbatim `get_outline()` → gates on `get_sections()` (text-bearing) instead. Heading-only divider sections legitimately have empty content and never get a `summary`; requiring 100% of outline nodes summarized would retry-forever. Gate only on sections that actually have text. |
| 19 | B3 abstract retry window? | **auto-decided (B3):** `generate_source_abstract` is submitted right after fanning out N per-section LLM jobs on one local GPU → `max_attempts=8, exponential_jitter, wait 15–120s` (~10 min). May need widening for 30+ chapter textbooks; manual re-run via `Source.summarize_sections()` remains. `summarize_section` retry = `max_attempts=3, fixed 5s, stop_on ValueError/ConfigError`. |
| 20 | citation → PDF-page-open (Q-citation-pdf-open)? | **PARKED FOLLOW-UP (from C4):** Phase3 forwards a `page` arg and C4 does section-anchor scroll, but opening the inline PDF at page N needs `SourceDetailContent.tsx` made tab-controlled + `PDFViewer.initialPage` wired + a `{activeTab, citationPage}` lift on the source page — all OUTSIDE any chunk's file ownership (Phase1 owns those, done). **Proposed default:** a small follow-up chunk (allowed to touch SourceDetailContent + source page + PDFViewer) closes it; `ChatPanel.handleReferenceClick` then takes the 3rd `page` arg. On the run's end punch-list. |
| 21 | Non-PDF "long" context after B4 (X-nonpdf-longcontext)? | **✅ RESOLVED (2026-07-02, orchestrator fix commit 8c0b606).** Reconciled #7 vs #12: `Source.get_context("long")` now falls back to `full_text` when `outline` is empty (covers non-PDF sources + a not-yet-chaptered PDF's transient window); `Notebook.get_context` re-fetches full_text (`include_full_text=True`) so the fallback has data; `format_source_long_context` renders the raw body when there are no chapters. Chaptered PDFs still return the tiered digest (no prompt balloon). Added regression test `test_notebook_get_context_falls_back_to_full_text_for_unchaptered_source`. Full suite 215 pass. Not a user decision — Decision #12 already mandated this; B4's literal spec merely contradicted it. |

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
- **Q-qwen-vision** — Is the deployed Ollama Qwen the vision build? Does Esperanto+Ollama forward image_url blocks?
  **Piloted 2026-07-02 (wave4):** YES — `qwen3.6:35b` handles image input correctly through the app's
  normal provisioning path. Quality: body text excellent (incl. an image-only page PyMuPDF got 0 chars
  from); both dense tables (IPA/phonetics, verb conjugation) reconstructed correctly; Greek
  script/diacritics handled well; two small transcription slips in dense prose (non-determinism); math
  untested (no sampled page had any). **Agent recommendation: GO-WITH-CAVEATS. Human-blessed 2026-07-02
  — B2 unblocked.** See b-pipeline.md Chunk B1 "Gate outcome" for the full pilot writeup.
- ~~**Q-vision-gate-bypass**~~ *(from B1 pilot)* — **RESOLVED 2026-07-02.** The DB-linked credential for
  the vision model (`credential:sl23md12zdmi5ok3v9bc`, "Default (Migrated from env)") stored
  `base_url=http://localhost:11434` directly, and credential config takes priority over env vars in
  `ModelManager.get_model` — so it bypassed the `:11435` heavy-slot admission-control gate entirely
  (this credential is also linked to `qwen3-embedding:8b`, so both modalities were affected). **Fixed:**
  `base_url` updated to `http://localhost:11435` via `Credential.save()`; verified the gate forwards both
  `/api/tags` and `/api/embeddings` correctly; `on-api`/`on-worker` restarted clean.
- **Q-section-content-payload** — Return `content` inline in the sections endpoint or lazy per-section fetch? *Default:* `summary` always inline; `content` only on demand (keep tree payload light). Revisit if UX needs it.
- **Q-viewer-peer-dep** — @react-pdf-viewer React 19/Next 16 compatibility. *Default:* Phase1 validates; fallback to react-pdf + custom highlight layer. Resolve in Phase1.
- **Q-section-delete-cleanup** *(new, from A3)* — `Source.delete()` does not remove orphaned `source_section`
  rows. *Default:* add `DELETE source_section WHERE source = $source_id` to `Source.delete()` (or a DB
  trigger). Low severity; fold into B (which already edits notebook.py) or a small follow-up. Tracked.
- ~~**Q-page-map-provenance**~~ *(from A3)* — **RESOLVED 2026-07-02 (design chosen, in Phase3 spec):**
  `page_map` gets **persisted** — migration 20 adds `source.page_map` (FLEXIBLE option<array>);
  `save_source` writes `state.page_map` at ingest; `embed_source` + `backfill_page_numbers` read it off
  the source record (backfill re-extracts when null + file present; else leaves `page_number` null).
  This was mandatory, not optional: `embed_source` is itself an out-of-process fire-and-forget command,
  so even the MAIN path could never see transient graph state. **Consequence:** Phase3 now edits
  `graphs/source.py` + `domain/notebook.py` → new shared-file rows above (B2/B ordering constraint).

---

## Changelog

- 2026-07-02 (post-wave5d fix) — **Decision #21 RESOLVED (commit 8c0b606).** Orchestrator integration-fix
  reconciling B4's #7 vs #12: non-chaptered sources (empty outline) now fall back to `full_text` in long
  context; `Notebook.get_context` re-fetches full_text; `format_source_long_context` renders the raw body
  when no chapters. Chaptered PDFs unchanged (digest). New regression test; **full suite 215 pass.** Applied
  (not parked) because Decision #12 already dictated the behavior — B4's literal spec contradicted it.
- 2026-07-02 (wave5d — final code wave) — **B4 ◐ (c6f6004), B5 ◐ (1effece). ALL document-foundation
  code landed.** 2 parallel worktree agents (both backend, file-disjoint; orchestrator pre-verified the
  `get_context` callers are opaque so B4 needn't touch api/). **B5** — `get_source_outline`/`get_section`
  MCP tools (conformed to the file's real dict-arg/`_result` pattern), `get_source` gets nav hints; 214
  pass, ruff clean, server builds. **B4** — tiered `Source.get_context("long")` (abstract+outline, no
  full_text) + `Notebook.get_context` rewire; 214 pass (2 tests updated). **B4 surfaced a real
  #7↔#12 conflict (Decision #21, PARKED for you):** non-PDF sources never chapter → empty long block,
  regressing Decision #12; recommended fallback in the Decisions log. Both left ◐ pending live checks.
  Merged-tree verify green vs baseline. **This closes the automated waves — a consolidated punch-list
  (Decisions #20/#21 + all live spot-checks) is now handed to the user; archival waits on it.**
- 2026-07-02 (wave5c) — **C4 ☑ (a530bfa) → Track C COMPLETE; B3 ◐ (abb9444).** 2 parallel worktree agents
  (B3 backend ‖ C4 frontend, disjoint). **C4** — Explain/Save-note in PassageSelectionMenu, per-chapter
  Summarize/Quiz in SourceTOC (chat dispatch via `onSectionAction` prop from SourceContentTab's
  `useSourceChat` — Q-c4-chat-scope resolved), ChatPanel citation→`data-section-id` scroll, 5 keys ×14;
  reuse-only (no duplicated dispatch), annotations stay OUT. Surfaced **Q-citation-pdf-open** (Decision
  #20) — the `#p=N`→open-PDF-at-page last mile needs page-owned files C4 can't touch; parked follow-up.
  **B3** — `summarize_section`/`generate_source_abstract` + `Source.summarize_sections()` fan-out +
  trigger after B2's verify. Left ◐ (live summary/abstract run parked). B3 auto-decisions #17–19 (abstract
  idempotency, `get_sections` readiness gate to avoid retry-forever, retry windows). Merged-tree verify:
  **backend full suite 214 pass**; frontend `tsc` clean (baseline only, 3 `@testing-library` test-file
  errors, zero new). Final code wave next: B4 ‖ B5.
- 2026-07-02 (wave5b) — **C3 ☑ (887bf95); B2 ◐ (09c0fed).** Orchestrated run, 2 parallel worktree agents
  (B2 backend ‖ C3 frontend, disjoint). **C3** — `SourceTOC.tsx` + two-column `SourceContentTab` reusing
  the single existing ReactMarkdown; chapter content fetched once via `getSections(id,true)`; unchaptered
  fallback (flat `full_text`) preserved; C2's nullable `title` tolerated; `data-section-id` anchors +
  `getSectionPageRangeLabel` exposed for C4. **B2** — `verify_clean_section` (PyMuPDF 2× page render →
  vision verifier → `cleaned_content`, raw `content`/`full_text` immutable; discrepancies → `verify_flag`
  SourceInsight) + `verify_clean_source` fan-out + fire-and-forget trigger in `submit_sections`. **Left ◐**
  — its deliverable ("cleaned visibly better than raw") is only confirmable on a live run (worker + real
  PDF + vision model). Three B2 auto-decisions recorded (see Decisions log #14–16). Merged-tree verify:
  `pytest tests/test_domain.py` 31 pass; verify_commands import+register OK; source graph imports; frontend
  `tsc` clean (baseline only). Next: B3 ‖ C4.
- 2026-07-02 (wave5) — **C2 ☑ (22eca7c); Phase3 ◐ (b525c88).** Orchestrated run (chunk-plan-execute,
  3 parallel worktree agents: bg D1 ‖ df C2 ‖ df Phase3). **C2** — `SourceSectionNode`/`SourceSectionResponse`
  TS types + `has_sections?`/`sections_count?` on `SourceDetailResponse` + `sourcesApi.getSections`.
  **Phase3** — migration 20 (`source.page_map` FLEXIBLE + `source_embedding.page_number`/`bbox` +
  `fn::vector_search` redefined via REMOVE+DEFINE, mig 4 untouched); `chunking.py` `build_page_char_map`/
  `find_chunk_page`; `embed_source` stamps `page_number` from persisted `source.page_map`;
  `backfill_page_numbers` command; `save_source` persists `state.page_map`; prompts emit `[source:id#p=N]`;
  `source-references.tsx` parses `#p=N` and forwards a `page` arg (C4 consumes it for the PDF-open wiring).
  Merged-tree verify: `pytest tests/test_domain.py tests/test_chunking.py` 65 pass; `test_models_api`
  isolated 12 pass; imports clean; mig 20 in both async_migrate lists; frontend `tsc` clean (baseline
  `@testing-library` test-file noise only). **Phase3 left ◐** — its Verify block is live (needs API restart
  for migration-apply, a real PDF re-embed, and browser citation click); those are on the run's punch-list.
  **B2 now unblocked** (Phase3 released `graphs/source.py`). Follow-up: C2's `title` is typed non-optional
  per the verbatim spec while the backend field is nullable — C3 should tolerate a null title.
- 2026-07-02 (wave4, post-gate) — **B1 human-blessed GO-WITH-CAVEATS; Q-vision-gate-bypass fixed.**
  `credential:sl23md12zdmi5ok3v9bc` (linked to both `qwen3-embedding:8b` and `qwen3.6:35b`) had
  `base_url` corrected `:11434` → `:11435` (the heavy-slot gate) via `Credential.save()`; verified the
  gate forwards `/api/tags` + `/api/embeddings`; `on-api`/`on-worker` restarted clean, `/api/sources`
  200. **B2 is now unblocked.**
- 2026-07-02 (wave4) — **C1 ☑ (c498aa4)** — recovered from a prior session's completed-but-unmerged
  worktree (`agent-a3289c0d50a2fd904`, orig commit `67c3b7d`, based only 1 docs-commit behind HEAD);
  cherry-picked clean, `pytest tests/test_models_api.py` 12 passed. **B1 plumbing ☑ (87de266), parked at
  human gate** — `default_vision_model`/`get_vision_model()`, `ai/vision_utils.py`, `graphs/chat.py`
  data_uri passthrough. Live pilot: `qwen3.6:35b` transcribed 3 real pages of a Modern Greek grammar PDF
  (image-only cover, 2 dense tables) — strong body-text/table/script fidelity, two small prose slips,
  math untested. Agent rec: GO-WITH-CAVEATS. Found + documented (not fixed): `max_tokens` silent-empty-
  output bug (must force ≥8192 in B2), and the shared vision-model credential bypasses the `:11435`
  heavy-slot gate (Q-vision-gate-bypass, needs human decision before any real B2 job runs). Two other
  worktrees found from the same stale-session batch (`agent-a37c36e19fb100271` orig `812a46b`,
  `agent-ac6b9d010feb91603` orig `5e88b34`) were confirmed byte-identical (diff-only-on-hash) to already-
  landed `e9bcafe`/`6ba9f40` — pure leftovers, no unique work, safe to discard.
- 2026-07-02 — **Phase3 design revision (Q-page-map-provenance resolved):** migration 20 now also adds
  `source.page_map` (persisted provenance); `save_source` persists it at ingest; embed/backfill read it
  from the record. Phase3's file set grew (`graphs/source.py`, `domain/notebook.py`) → new shared-file
  rows: **Phase3 must not run in the same wave as B2 (graphs/source.py) or any B chunk
  (domain/notebook.py)**. Meta-coordinator Wave 5 packing updated accordingly (it had B2 ‖ Phase3
  concurrent). Also noted in c-surfaces context: C4's `ChatPanel.tsx` edit is now tracked in the
  meta-coordinator cross-lane table (chat-foundation F4 collides; F4 → C4 order).
- 2026-06-29 — Wave-3: **A3 ☑ (6ba9f40)** — chaptering. `commands/section_commands.py`
  (`build_sections` + `backfill_sections`), `Source.get_sections()`/`get_outline()`, graph rewired
  `save_source → submit_sections → trigger_transformations` (fire-and-forget), `embed_source` stamps
  `section` on `source_embedding`. Boundary detection = PyMuPDF `get_toc()` → Docling heading fallback →
  single section (Decision #4). Verified: `pytest tests/test_domain.py` 31 pass; worker registers 16
  commands (build_sections+backfill_sections); api starts clean. Live-ingest spot-check pending (manual,
  on punch-list). **Track A FULLY ☑ → Track B, Track C, and Phase3 all unblocked.** Two follow-ups filed:
  Q-section-delete-cleanup, Q-page-map-provenance (see Open Questions).
- 2026-06-29 — Reconciliation (resumed orchestrator): **A2 ☑ (7e13d72)** Docling extraction +
  page_map provenance (`content-core[docling]`, `_extract_docling_page_map()`, PyMuPDF fallback;
  Q-docling-install resolved — docling 2.x imports clean); **Phase1 ☑ (1608053)** inline PDFViewer
  (@react-pdf-viewer + Original PDF tab + next.config worker alias + 14 locales). Both committed by
  prior sessions but never recorded — now reflected in all status tables. Outstanding **manual**
  spot-checks (not blocking): A2 GPU extraction on a real textbook; Phase1 in-browser PDF render.
  **A3 now runnable (deps A1 ✓ + A2 ✓); Phase3 unblocked once A3 ☑.**
- 2026-06-26 — Document-foundation plan authored. Supersedes source-chaptering/ and
  pdf-viewer-citations.md. Migration 19 for Track A, 20 for Phase3. Post-refactor paths confirmed
  (sources.py → package; SourceDetailContent → detail/; SourceContentTab owns ReactMarkdown render;
  PassageSelectionMenu in notebooks/workspace/). Wave 0 / P3 ☑ in meta-coordinator.
