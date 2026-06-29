# Document Foundation — Track A: Foundation (migration + extraction + chaptering)

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared
> decisions, conventions, concurrency, file ownership — then execute this track's chunks here,
> one per session. **Location:** `.claude/plans/document-foundation/a-foundation.md` →
> archived with the directory when all tracks ☑.

## SESSION HANDOFF — resume here

**Track deps:** none — **this track runs first.** B, C, and Phase3 are all blocked until specific
chunks here are ☑. Phase1 is independent (can run in parallel).

**Paste-able resume prompt (run in a fresh chat):**
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/a-foundation.md in full. Implement the next unstarted chunk
(one only — derive from the Status table + `git log --oneline -30`, respecting A1 → A2 → A3 order).
Verify per the chunk's verify instructions. Commit (one chunk = one commit). Update BOTH this
file's Status table AND the coordinator's Global status table + Changelog. Announce
"✅ Chunk A.n complete — safe to clear context. Next: A.(n+1)" and stop.
```

**State at handoff (2026-06-26):** Plan authored; no chunks started.

---

## This track's file ownership

Creates/modifies (Track A only — no other track touches these until A☑):

| File | Chunk | What changes |
|------|-------|-------------|
| `open_notebook/database/migrations/19.surrealql` | A1 | New migration (source_section table + source fields + source_embedding field) |
| `open_notebook/database/migrations/19_down.surrealql` | A1 | Down migration |
| `open_notebook/database/async_migrate.py` | A1 | Append mig 19 to up + down lists |
| `open_notebook/domain/notebook.py` | A1, A3 | A1: add SourceSection model + page_offset to Source; A3: add get_sections/get_outline methods |
| `open_notebook/graphs/source.py` | A2, A3 | A2: Docling extraction; A3: structure/chaptering node |
| `open_notebook/config.py` | A2 | Docling config flag (if not already present) |
| `pyproject.toml` | A2 | Add docling dependency (verify it isn't already added) |
| `commands/section_commands.py` | A3 | New: backfill_sections command |
| `open_notebook/utils/chunking.py` | A3 | Stamp section on chunks |
| `commands/embedding_commands.py` | A3 | Stamp section on source_embedding rows |

**Hand-off to B:** after A☑, B extends `notebook.py` (get_context + summarize/cleaned helpers),
`graphs/source.py` (fire-and-forget triggers), and new `commands/` files.
**C must NOT touch** any file in this table.
**Phase3 must wait for A1☑ (async_migrate.py) and A3☑ (chunking.py + embedding_commands.py).**

---

## Per-chunk workflow

read referenced files → implement → verify → mark ☑ here AND in coordinator → note new Open
Questions → commit (one chunk = one commit) → announce "✅ Chunk A.n complete — safe to clear
context" → stop.

---

## Status table (this track)

| Chunk | Title | Status | Notes |
|------:|-------|--------|-------|
| A1 | Migration 19 + SourceSection model + page/section fields | ☑ | commit 34ec0bd; source_section + source.page_offset/page_labels + source_embedding.section verified live in DB |
| A2 | Docling extraction + page provenance | ☑ | commit 7e13d72; content-core[docling]>=1.14.1 + _extract_docling_page_map() + page_map on SourceState + PyMuPDF fallback. Q-docling-install resolved (docling 2.x installed). ⚠ GPU spot-check on real textbook still pending (manual) |
| A3 | Chaptering: section tree + get_sections/get_outline + tagged chunks + backfill | ☑ | commit 6ba9f40; section_commands.py (build_sections+backfill_sections), Source.get_sections/get_outline, graph rewired save_source→submit_sections→trigger_transformations, embed_source stamps section. pytest test_domain 31 pass; worker registers 16 cmds; api starts clean. ⚠ live-ingest spot-check (real textbook→tree) pending (manual). wave3 2026-06-29 |

Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked

---

## Changelog (this track)

- _(none yet.)_

---

## Chunks (verbatim)

---

### Chunk A1 — Migration 19 + SourceSection model + page/section fields

**Goal:** Add all schema this feature needs in one additive migration, plus the `SourceSection`
domain model. Nothing destructive — `full_text` and all existing columns are untouched.

**Read first:**
- `open_notebook/database/migrations/1.surrealql` — source/source_embedding/source_insight defs
- `open_notebook/database/migrations/17.surrealql` — latest (chat_tag_colors; see field DEFINE pattern)
- `open_notebook/database/async_migrate.py` lines ~98–128 (hard-coded `up_migrations` list) and ~174–181 (down list); `bump_version()`
- `open_notebook/domain/notebook.py` — `SourceInsight` (323–351) and `SourceEmbedding` (304–320) as model patterns; `Source` (354–620) for `nullable_fields`

**Exact spec:**

`migrations/19.surrealql`:
```surql
-- Migration 19: document-foundation — source_section table + page/section fields

-- Chapter/section tree for structured documents (PDFs, long-form content)
DEFINE TABLE IF NOT EXISTS source_section SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS source        ON TABLE source_section TYPE record<source>;
DEFINE FIELD IF NOT EXISTS parent        ON TABLE source_section TYPE option<record<source_section>>;
DEFINE FIELD IF NOT EXISTS order         ON TABLE source_section TYPE int;
DEFINE FIELD IF NOT EXISTS level         ON TABLE source_section TYPE int;
DEFINE FIELD IF NOT EXISTS title         ON TABLE source_section TYPE string;
DEFINE FIELD IF NOT EXISTS content       ON TABLE source_section TYPE string;
DEFINE FIELD IF NOT EXISTS cleaned_content ON TABLE source_section TYPE option<string>;
DEFINE FIELD IF NOT EXISTS summary       ON TABLE source_section TYPE option<string>;
DEFINE FIELD IF NOT EXISTS page_start    ON TABLE source_section TYPE option<int>;
DEFINE FIELD IF NOT EXISTS page_end      ON TABLE source_section TYPE option<int>;
DEFINE FIELD IF NOT EXISTS token_count   ON TABLE source_section TYPE option<int>;
DEFINE FIELD IF NOT EXISTS created       ON TABLE source_section TYPE datetime DEFAULT time::now();
DEFINE FIELD IF NOT EXISTS updated       ON TABLE source_section TYPE datetime DEFAULT time::now();

-- Physical page anchor for label→index mapping
DEFINE FIELD IF NOT EXISTS page_offset   ON TABLE source TYPE option<int>;
DEFINE FIELD IF NOT EXISTS page_labels   ON TABLE source FLEXIBLE TYPE option<object>;

-- Section link on embeddings (populated by embed_source after chaptering)
DEFINE FIELD IF NOT EXISTS section       ON TABLE source_embedding TYPE option<record<source_section>>;
```

`migrations/19_down.surrealql`:
```surql
REMOVE TABLE source_section;
REMOVE FIELD page_offset  ON TABLE source;
REMOVE FIELD page_labels  ON TABLE source;
REMOVE FIELD section      ON TABLE source_embedding;
```

`async_migrate.py` — append `"open_notebook/database/migrations/19.surrealql"` to the
`up_migrations` list and `"open_notebook/database/migrations/19_down.surrealql"` to the down list.

`notebook.py` — add before or after `SourceEmbedding`:
```python
class SourceSection(ObjectModel):
    table_name = "source_section"
    source: Optional[str] = None
    parent: Optional[str] = None
    order: int = 0
    level: int = 0
    title: str = ""
    content: str = ""
    cleaned_content: Optional[str] = None
    summary: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    token_count: Optional[int] = None
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    nullable_fields = ["parent", "cleaned_content", "summary", "page_start", "page_end", "token_count", "created", "updated"]
```

Also add `page_offset: Optional[int] = None` and `page_labels: Optional[dict] = None` to the
`Source` model, and add both to its `nullable_fields` list.

**Verify:**
1. Restart the API → logs show `migration 19 applied` and version bumped to 19.
2. `SourceSection.get(...)` resolves without error.
3. Existing source CRUD (list/get/create/delete) unaffected.
4. `uv run pytest tests/test_domain.py` — green.

---

### Chunk A2 — Docling extraction + page provenance

**Goal:** For PDFs, extract via Docling → structured markdown `full_text` AND per-block
`(text, page_no)` provenance map. Keep PyMuPDF as fallback. This is the fidelity foundation for
chaptering and the ground-truth page-image slicing in B2.

**Read first:**
- `open_notebook/graphs/source.py` — `SourceState` (19–26), `content_process` (34–107; esp.
  engine config ~54–60 and `extract_content` @78), `save_source` (110–140)
- `open_notebook/domain/content_settings.py` — `default_content_processing_engine_doc`
- `pyproject.toml` — current dependencies (check if `content-core[docling]` is already present)
- `.claude/plans/document-foundation/coordinator.md` Decision #1, Q-docling-install

**Spec / exact values:**

1. **Add Docling dependency:** check if `content-core[docling]` or `docling` is already in
   `pyproject.toml`. If not, add it. Verify `uv lock` resolves for aarch64+CUDA (Spark). If model
   weights must be pre-baked, add a download step to `Makefile` or document it.

2. **`SourceState` extension:** add an optional field `page_map: Optional[List[Dict]] = None`
   (list of `{"text": str, "page_no": int}` dicts from Docling per-block provenance).

3. **`content_process` node:** for PDF sources, run Docling (prefer via the existing
   `document_engine: docling` config path in content-core if it exposes per-block page_no; otherwise
   call Docling directly for PDFs). Capture:
   - `full_text` — the structured markdown (headings, tables, lists) from Docling
   - `page_map` — list of `{"text": str, "page_no": int}` from `result.document` provenance
   Store both on `SourceState`; the chaptering step (A3) reads `page_map`.
   On any Docling failure: log the error, fall back to the existing PyMuPDF path, set `page_map = None`.

4. **`save_source` node:** no changes — continues to write `state["full_text"]` to `Source.full_text`
   as the immutable raw parse. Docling's structured markdown IS the `full_text` for PDFs.

5. **Non-PDF sources:** unchanged — skip Docling, no `page_map`.

**Open Question (resolve here):** Q-docling-install — aarch64+CUDA wheel, model-weights download,
license check. Record the outcome in the coordinator's Open Questions.

**Verify:**
1. Ingest a real textbook PDF on the Spark → `source.full_text` shows genuine heading structure
   (`#`/`##`), not a flat wall of text.
2. `SourceState.page_map` is populated (non-empty list of text+page_no dicts).
3. Ingest a non-PDF source (web page, pasted text) → still ingests via the existing path, no regression.
4. Simulate a Docling failure (e.g. temporarily pass a corrupt file) → fallback to PyMuPDF, no crash.
5. `uv run pytest tests/` — green.

---

### Chunk A3 — Chaptering: section tree + get_sections/get_outline + tagged chunks + backfill

**Goal:** Turn the parsed markdown into an ordered `source_section` tree on ingest. Expose it via
`Source.get_sections()` / `get_outline()`. Tag each embedding chunk with its section. Provide a
backfill command for existing sources.

**Read first:**
- `open_notebook/graphs/source.py` — wiring at 185–200 (where to add node after `save_source`)
- `commands/source_commands.py` `process_source_command` (49–113) — command pattern
- `commands/embedding_commands.py` `embed_source` (365–501) — bulk insert + the `section` field to stamp
- `open_notebook/utils/chunking.py` `chunk_text` (419–494) — chunk construction
- `open_notebook/domain/notebook.py` — `Source` methods; the new `SourceSection` from A1

**Spec / exact values:**

**Boundary detection strategy (Decision #4):**
1. PyMuPDF `doc.get_toc()` → returns `[[level, title, start_page], ...]` (physical pages). If non-empty, use these as chapter boundaries.
2. If `get_toc()` is empty: derive chapters from Docling heading levels + `page_no` from `page_map` (A2). Walk `page_map` entries; when a heading block starts a new section, record level + page.
3. If neither: one section spanning the whole document (= current behavior, no crash).

**Section records:**
- Each `source_section` stores: `source`, `parent` (record id of parent section or null), `order` (0-indexed sibling position), `level` (1=top-level chapter, 2=sub-section, ...), `title`, `content` (the markdown slice for this section's page range), `page_start`, `page_end` (physical indices), `token_count` (len of content in tokens, approximate via `len(content.split())`).
- `page_start`/`page_end` are **physical** page indices (0-based).

**`Source.get_sections()` on notebook.py:** query `source_section WHERE source = $source_id ORDER BY order`, reconstruct the nested tree (build dict by id, assign children), return root-level list.

**`Source.get_outline()` on notebook.py:** same query but return only `{id, title, level, order, page_start, page_end, summary}` — no `content`. Used for the agent context and the TOC sidebar.

**Graph wiring:** add a `structure` step after `save_source` in `graphs/source.py` — either as a new `structure` node that calls `build_sections(source_id, page_map)` synchronously (acceptable since cost/speed aren't constraints), OR as a fire-and-forget `submit_command("open_notebook", "build_sections", {"source_id": ...})`. Prefer the command approach so it's retriable and shows up in the job queue.

**Chunk stamping:** in `embed_source` (`commands/embedding_commands.py`), after creating each chunk from `chunk_text`, look up which `source_section` the chunk belongs to (match by character offset or page range) and stamp `section = source_section_id` on the `source_embedding` insert. If no sections exist (non-PDF or chaptering not yet run), `section = None`.

**Backfill command:** `commands/section_commands.py` with `@command("build_sections")` taking `{source_id}` → runs the full chaptering pipeline for one source. An orchestrator `backfill_all_sections` fans out `build_sections` for all existing PDF sources.

**page_offset anchor:** auto-detect via PyMuPDF `doc.page_labels` (if available). Store detected `page_offset` on `Source.page_offset`. Default null = identity (page index 0 = printed page 1).

**Verify:**
1. Ingest a bookmarked textbook PDF → `source_section` rows form a correct tree; `Source.get_sections()` returns it nested; `Source.get_outline()` returns chapter titles + page ranges.
2. `source_embedding` rows carry `section` (non-null for PDF sources that have chapters).
3. Run `backfill_sections` on a pre-existing source → it chapters correctly.
4. Ingest a headingless PDF → produces exactly one section (no crash).
5. `uv run pytest tests/` — green.

---

## Open Questions (this track)

- **Q-docling-install** — Resolve in A2. Default: add `content-core[docling]` extra; if aarch64 wheel unavailable, call Docling directly; pre-bake model download into Docker image.
- **Q-toc-quality** — `get_toc()` may give coarse or missing bookmarks on some PDFs. Default: Docling-heading fallback; headingless → single section. Revisit only if real textbooks chapter poorly.
- **Q-section-command-sync-or-async** — Build sections synchronously as part of the ingest graph, or as a fire-and-forget command? Default: fire-and-forget command (retriable, queueable, shows in job tray). The ingest graph just submits the command after `save_source`.
