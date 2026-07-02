# Source Chaptering — Track A: Foundation (data model + extraction + chaptering)

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared decisions,
> conventions, concurrency, file ownership — then execute this track's chunks here, one per session.
> **Location:** `.claude/plans/source-chaptering/a-foundation.md` → archived with the directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** none — **this track runs first.** Tracks B and C are blocked until every A chunk is ☑.
**Concurrent with:** nothing (head of critical path).
**State at handoff (2026-06-22):** planning complete; no chunks started.
**Paste-able resume prompt (run in a fresh chat):**
> Continue Source-Chaptering Track A (Foundation). Read `.claude/plans/source-chaptering/coordinator.md`
> then `.claude/plans/source-chaptering/a-foundation.md` in full. Implement the next unstarted chunk (one
> only), verify it, then update BOTH this file's Status table AND the coordinator's Global status table +
> Changelog, and tell me when it's safe to clear context.

## This track's file ownership
Creates/modifies: `open_notebook/database/migrations/17.surrealql`, `17_down.surrealql`,
`open_notebook/database/async_migrate.py`, `open_notebook/domain/notebook.py` (add `SourceSection` model +
`Source.get_sections`/`get_outline` + `page_offset`), `open_notebook/graphs/source.py` (structure wiring),
a new `commands/section_commands.py`, `open_notebook/utils/chunking.py` (section-aware tagging),
`commands/embedding_commands.py` (stamp `section` on chunks), `pyproject.toml` + `open_notebook/config.py`
(Docling dep/config).
**Hand-off to B:** after A ☑, B extends `notebook.py`/`source.py`/`commands/`. **C must never touch these.**

## Per-chunk workflow
read referenced files → implement → verify → mark ☑ here AND in the coordinator → note new Open Questions →
announce "✅ Chunk A.n complete — safe to clear context" → stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| A1 | Migration 17 + `SourceSection` model + page/section fields | ☐ todo | | foundation |
| A2 | Docling extraction + page provenance | ☐ todo | | coordinate w/ pdf-viewer plan |
| A3 | Chaptering: structure node + section tree + `get_sections`/`get_outline` + section-tagged chunks + backfill | ☐ todo | | |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet.)_

## Chunks (verbatim)

### Chunk A1 — Migration 17 + `SourceSection` model + page/section fields
- **Goal:** Add all schema this feature needs, in one additive migration, plus the `SourceSection` domain
  model. Nothing destructive — `full_text` is untouched.
- **Read first:** `open_notebook/database/migrations/1.surrealql` (source/source_embedding/source_insight
  defs), `16.surrealql` (latest), `open_notebook/database/async_migrate.py` (the hard-coded `up_migrations`
  list ~98-127 and down list ~174-176, `bump_version`), `open_notebook/domain/notebook.py` (`SourceInsight`
  323-351 and `SourceEmbedding` 304-320 as model patterns; `Source` 354-620).
- **Spec / exact values:** See coordinator Decisions #4, #8, #10. Migration `17.surrealql`:
  - `DEFINE TABLE IF NOT EXISTS source_section SCHEMAFULL;` with fields: `source record<source>`,
    `parent option<record<source_section>>`, `order int`, `level int`, `title string`,
    `content string` (raw parsed markdown slice for this section), `cleaned_content option<string>`
    (B fills later), `summary option<string>` (B fills later), `page_start option<int>`,
    `page_end option<int>` (physical indices), `token_count option<int>`, plus `created`/`updated` like
    other tables.
  - `DEFINE FIELD IF NOT EXISTS page_offset ON TABLE source TYPE option<int>;` (Decision #8 anchor) and
    optionally `page_labels option<object>`.
  - `DEFINE FIELD IF NOT EXISTS section ON TABLE source_embedding TYPE option<record<source_section>>;`
    (A3 stamps it).
  - `17_down.surrealql`: `REMOVE TABLE source_section;` + remove the added fields (`REMOVE FIELD …`).
- **Reuse:** the `ObjectModel` subclass shape of `SourceInsight`/`SourceEmbedding` for the new
  `SourceSection(ObjectModel)` (`table_name="source_section"`, typed fields, `nullable_fields` for the
  option fields).
- **Steps:** (1) write `17.surrealql` + `17_down.surrealql`; (2) append both to the lists in
  `async_migrate.py`; (3) add `SourceSection` model to `notebook.py`; add `page_offset` field to `Source`
  (declare in `nullable_fields`); (4) no behavior change to ingest yet.
- **Verify:** start the API → logs show migration 17 applied, version bumped to 17; `SourceSection.get(...)`
  resolves; existing source CRUD unaffected; `uv run pytest tests/test_domain.py` green.

### Chunk A2 — Docling extraction + page provenance
- **Goal:** For PDFs, extract via **Docling** → structured markdown `full_text` **and** per-block
  `(text, page_no)` provenance; keep PyMuPDF as fallback. This is the fidelity foundation for chaptering and
  ground-truth slicing.
- **Read first:** `open_notebook/graphs/source.py` `content_process` (34-107, esp. engine config 54-60 and
  `extract_content` @78) and `save_source` (110-140); `open_notebook/domain/content_settings.py`
  (`default_content_processing_engine_doc`); `.claude/plans/pdf-viewer-citations.md` Phase 2 (shared Docling).
- **Spec / exact values:** Decision #3. content-core already ships a Docling wrapper
  (`document_engine: auto|simple|docling`); prefer driving it through the existing `document_engine` config
  rather than calling Docling directly, if that exposes page provenance. If not, call Docling directly for
  PDFs and fall back to the current `extract_content` path otherwise.
- **Reuse:** the existing `content_state`/`ProcessSourceState` flow; `output_format="markdown"` stays.
  PyMuPDF (`fitz`) is already a transitive dep — use it for the fallback and (A3) for `get_toc`/`get_pixmap`.
- **Steps:** (1) add the Docling dependency (verify it isn't already added by the pdf-viewer plan — if so,
  reuse); (2) in `content_process`, for PDF sources select Docling and capture both markdown and the
  per-block `page_no` list; (3) thread the page map into `SourceState` (new optional field, e.g.
  `page_map`) so A3's chaptering can read it; (4) keep `save_source` writing `full_text` as today (raw parse,
  immutable); (5) graceful fallback to PyMuPDF on any Docling failure.
- **Verify:** ingest a real textbook PDF → `full_text` shows genuine heading structure (`#`/`##`), not a flat
  wall; the page map is populated; a non-PDF source still ingests via the old path. Spot-check on the Spark
  (GPU) per Decision #2.
- **Open Question:** Q-docling-install (coordinator) — aarch64+CUDA wheel, model weights, license. Resolve
  here or flag.

### Chunk A3 — Chaptering: structure node + section tree + `get_sections`/`get_outline` + section-tagged chunks + backfill
- **Goal:** Turn the parsed markdown into an ordered `source_section` tree on ingest; expose it via
  `Source.get_sections()` / `get_outline()`; tag each embedding chunk with its section; provide a backfill
  command for existing sources.
- **Read first:** `open_notebook/graphs/source.py` (wiring 185-200, where to add a node after `save_source`);
  `commands/source_commands.py` `process_source_command` (49-113) + `commands/embedding_commands.py`
  `embed_source` (365-501) for the command + bulk-insert patterns; `utils/chunking.py` `chunk_text` (419-494);
  `notebook.py` `Source` methods + the new `SourceSection` from A1.
- **Spec / exact values:** Decisions #5, #8. Boundary detection: PyMuPDF `doc.get_toc()` →
  `[[level, title, start_page], …]` (physical pages) first; if empty, derive from Docling heading levels +
  `page_no` (A2's page map); if neither, one section spanning the whole doc. Sections store the markdown
  **slice** for their page range as `content`; `page_start`/`page_end` are **physical** indices.
- **Reuse:** `submit_command`/`@command` pattern; `repo_insert`/`repo_query` for bulk section + chunk writes;
  `chunk_text` unchanged (just stamp the resulting `source_embedding` rows with their `section`).
- **Steps:** (1) add a `structure` step after `save_source` (a node or a fire-and-forget
  `submit_command("open_notebook","build_sections",{source_id})`); (2) implement section-tree construction
  (boundaries → `source_section` records with `parent`/`order`/`level`/`page_start`/`page_end`/`content`/
  `token_count`); (3) add `Source.get_sections()` (full tree) and `Source.get_outline()` (titles + page ranges
  + `summary` placeholders) to `notebook.py`; (4) stamp `section` on each `source_embedding` row at embed time
  (`embedding_commands.py`); (5) add a `backfill_sections` command that fans out over existing sources;
  (6) record/confirm the `page_offset` anchor flow (auto-detect `PageLabels`, else accept the value from the
  upload step — the API field for that lands in Track C, default null = identity offset for now).
- **Verify:** ingest a bookmarked textbook PDF → `source_section` rows form a correct tree;
  `Source.get_sections()` returns it nested; `Source.get_outline()` returns chapter titles + page ranges;
  `source_embedding` rows carry `section`; `backfill_sections` chapter-izes a pre-existing source; a
  headingless PDF yields a single section (no crash).

## Open Questions (this track)
- **Q-docling-install** — see coordinator. Default: behind `document_engine` config + PyMuPDF fallback.
- **Q-toc-quality** — `get_toc()` may give coarse or missing bookmarks. *Default:* Docling-heading fallback;
  headingless → single section. Revisit only if real textbooks chapter poorly.
