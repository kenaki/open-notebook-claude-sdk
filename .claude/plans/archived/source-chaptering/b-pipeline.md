# Source Chaptering — Track B: Backend pipeline (verify-clean → summaries → tiered context → agent tools)

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared decisions,
> conventions, concurrency, file ownership — then execute this track's chunks here, one per session.
> **Location:** `.claude/plans/source-chaptering/b-pipeline.md` → archived with the directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** **Track A must be ☑** (needs the `source_section` table, `Source.get_sections/get_outline`,
section-tagged chunks). Check the coordinator's Global status table before starting.
**Concurrent with:** **Track C** — safe to run at the same time (C touches only `api/*` + `frontend/*`; B
touches backend domain/graph/commands/ai). No shared files.
**State at handoff (2026-06-22):** planning complete; no chunks started.
**Paste-able resume prompt (run in a fresh chat):**
> Continue Source-Chaptering Track B (Backend pipeline). Read `.claude/plans/source-chaptering/coordinator.md`
> then `.claude/plans/source-chaptering/b-pipeline.md` in full. Confirm Track A is ☑ in the coordinator.
> Implement the next unstarted chunk (one only), verify it, then update BOTH this file's Status table AND the
> coordinator's Global status table + Changelog, and tell me when it's safe to clear context.

## This track's file ownership
Creates/modifies: `open_notebook/ai/models.py` (+ `provision.py`), a new `commands/verify_commands.py`, a new
`commands/summary_commands.py`, `open_notebook/graphs/transformation.py` (reuse), `open_notebook/domain/notebook.py`
(`get_context`, summarize + cleaned helpers), `open_notebook/utils/context_builder.py`,
`open_notebook/ai/claude_agent_tools.py`, `open_notebook/graphs/source.py` (fire-and-forget triggers).
**Do NOT add migrations** — all schema shipped in A1 (migration 17). **Do NOT touch `api/*` or `frontend/*`** (Track C).

## Per-chunk workflow
read referenced files → implement → verify → mark ☑ here AND in the coordinator → note new Open Questions →
announce "✅ Chunk B.n complete — safe to clear context" → stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| B1 | Vision-verifier plumbing + **validation-gate pilot** | ☐ todo | | gate before B2 |
| B2 | Per-chapter verify-clean background command | ☐ todo | | page-image ground truth |
| B3 | Per-section summaries + doc abstract | ☐ todo | | reuse insight engine |
| B4 | Tiered `get_context` rewrite | ☐ todo | | the digestion fix |
| B5 | Agent tools `get_source_outline` / `get_section` | ☐ todo | | |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet.)_

## Chunks (verbatim)

### Chunk B1 — Vision-verifier plumbing + validation-gate pilot
- **Goal:** Make a vision/multimodal model invokable through the stack, and **prove** the deployed local
  model can actually read a dense textbook page before any verify work depends on it.
- **Read first:** `open_notebook/ai/models.py` `DefaultModels` (62-95, `default_vision_model` is commented
  out) + `ModelManager.get_default_model` (221-264); `open_notebook/ai/provision.py` (10-61);
  `open_notebook/graphs/chat.py` `_attach_media_blocks` (70-105, inlines images as data-URIs on a
  `HumanMessage`); coordinator Decision #7 + Q-qwen-vision.
- **Spec / exact values:** Decision #7. There is **no** Esperanto vision factory; the working path is
  "provision a vision-capable chat model like any language model, then attach image blocks."
- **Reuse:** `_attach_media_blocks` (lift/share it so a command can build image blocks too); the existing
  `provision_langchain_model` path; the credential/Ollama plumbing already in place.
- **Steps:** (1) add `default_vision_model` to `DefaultModels` and a getter in `ModelManager`; (2) add a small
  helper to provision a vision model + build a `HumanMessage` with text + page-image data-URIs; (3) **PILOT
  (the gate):** render one dense page (PyMuPDF `get_pixmap`), send it + a "transcribe/verify this page" prompt
  to the deployed Ollama Qwen, and inspect output quality. (4) If quality is inadequate, record the fallback
  decision (cloud vision for verify-only, or text-only dual-parse) and adjust B2's design accordingly.
- **Verify:** the pilot returns a faithful reading of the page (text, a table, some math). Document the
  result in the coordinator's Open Questions (resolve Q-qwen-vision). Do **not** proceed to B2 until the gate
  passes or a fallback is chosen.

### Chunk B2 — Per-chapter verify-clean background command
- **Goal:** A background command that, for **one** section, renders its page images as ground truth, feeds
  them + the parsed `content` to the vision verifier, and writes a corrected `cleaned_content` — leaving the
  raw parse immutable. Run one section per invocation (context reset); fan out across a source's sections.
- **Read first:** `commands/embedding_commands.py` `create_insight_command` (738-820) + `process_source_command`
  (`commands/source_commands.py:49-113`) for the command shape; `SourceSection` (from A1) + `Source.get_sections`
  (from A3); B1's vision helper; `page_offset` on `Source` (physical-index slicing).
- **Spec / exact values:** Decisions #6, #8, #10. Ground truth = PyMuPDF `get_pixmap` over the section's
  `page_start..page_end` **physical** range. Prompt the verifier to fix parser artifacts (column merges,
  header/footer interleaving, hyphenation, tables, math) and to **flag** anything it can't reconcile, NOT to
  paraphrase. Write to `source_section.cleaned_content`; never overwrite `full_text` or `content`.
- **Reuse:** the `@command`/`submit_command` pattern; `repo_query` updates; B1's vision provisioning;
  fire-and-forget triggering from `graphs/source.py` after chaptering (A3).
- **Steps:** (1) `commands/verify_commands.py` with `@command("verify_clean_section")` taking
  `{source_section_id}` → render images → call vision model → store `cleaned_content` (+ a discrepancy note,
  e.g. as a `SourceInsight` type `"verify_flag"`); (2) an orchestrator/backfill that fans out one job per
  section of a source; (3) trigger it fire-and-forget after A3's chaptering (and expose it for re-runs);
  (4) keep retries bounded; the job holds no cross-chapter state (context reset by construction).
- **Verify:** run on one real section → `cleaned_content` populated and visibly better than `content`; raw
  `full_text`/`content` unchanged (diff-able); discrepancy flags recorded; a multi-section source fans out and
  each section completes independently; failure of one section doesn't poison others.

### Chunk B3 — Per-section summaries + doc abstract
- **Goal:** Generate a summary for each section and one document-level abstract, stored as derived layers, so
  the viewer and the agent context have a compressed map.
- **Read first:** `open_notebook/graphs/transformation.py` `run_transformation` (23-68); `Source.add_insight`
  (`notebook.py:525-570`) + `SourceInsight` (323-351); `SourceSection.summary` field (A1).
- **Spec / exact values:** Decision #4. Per-section summary → `source_section.summary`. Doc abstract →
  `SourceInsight` with `insight_type="abstract"` (reuses the insight + embed pipeline, no new table). Summaries
  run over the **cleaned_content** when present (B2), else `content`. Model = `default_transformation_model`
  (Qwen) or the large-context model for the abstract roll-up.
- **Reuse:** the transformation/insight engine (`provision_langchain_model(..., "transformation", ...)`,
  `clean_thinking_content`, `add_insight`); `submit_command` for fire-and-forget like existing insights.
- **Steps:** (1) `commands/summary_commands.py` with a per-section summarize command writing
  `source_section.summary`; (2) a doc-abstract step that rolls up the section summaries → `add_insight("abstract", …)`;
  (3) `Source.summarize_sections()` helper on `notebook.py` to fan out; (4) trigger fire-and-forget after B2
  (so summaries reflect cleaned text), with a manual re-run path.
- **Verify:** after running, each `source_section` has a `summary`; the source has an `"abstract"` insight;
  `Source.get_outline()` (A3) now surfaces real per-chapter summaries; re-running regenerates cleanly.

### Chunk B4 — Tiered `get_context` rewrite (the digestion fix)
- **Goal:** Stop dumping raw `full_text` into chat context. Default context = title + doc abstract + chapter
  outline (titles + per-chapter summaries) + on-demand `vector_search` retrieval.
- **Read first:** `Notebook.get_context` (`notebook.py:69-127`), `Source.get_context` (427-440), all callers
  via `grep get_context` (esp. `utils/context_builder.py:170,280`); `vector_search` (744-774).
- **Spec / exact values:** Decisions #9, #10. Keep the dict keys callers already read (`id`, `title`,
  `insights`) and **add** `abstract` + `outline`; **stop** returning `full_text` by default in `"long"`.
  Update `context_builder.py` to format abstract + outline instead of the raw blob. Retrieval stays via the
  existing `vector_search` (now section-aware from A3).
- **Reuse:** existing `get_insights`, `get_outline` (A3), `vector_search`; the `context_builder` formatting
  structure.
- **Steps:** (1) change `Source.get_context("long")` to return `{id,title,insights,abstract,outline}`
  (no `full_text`); (2) update `Notebook.get_context` + `context_builder.py` to render the new shape;
  (3) ensure retrieval is still wired for detail drill-in; (4) leave the `/chat` endpoint signature unchanged.
- **Verify:** a notebook chat over a large source no longer balloons the prompt with the whole textbook;
  the model receives the abstract + chapter outline and can still answer detail questions via retrieval;
  `uv run pytest tests/` green; no caller of `get_context` breaks (grep-confirmed).

### Chunk B5 — Agent tools `get_source_outline` / `get_section`
- **Goal:** Give the Claude Agent navigation tools so it pulls the outline and drills into specific sections
  instead of receiving the whole source.
- **Read first:** `open_notebook/ai/claude_agent_tools.py` (the `@tool` pattern + `create_sdk_mcp_server`,
  existing `get_source`/`search`); `Source.get_outline`/`get_sections` (A3).
- **Spec / exact values:** two new tools — `get_source_outline(source_id)` → chapter outline + summaries;
  `get_section(source_id, section_id)` → that section's cleaned/raw content. Register both in the MCP server.
- **Reuse:** the exact `@tool(name, desc, schema)` + `_result(...)` JSON-content pattern already in the file.
- **Steps:** (1) add the two `@tool` functions; (2) add them to the `create_sdk_mcp_server` tools list;
  (3) optionally adjust `get_source` to return the outline + a hint rather than full text.
- **Verify:** the agent can call `get_source_outline` then `get_section`; tool output is well-formed JSON;
  an agent chat answers a chapter-specific question by drilling in; no regression to existing tools.

## Open Questions (this track)
- **Q-qwen-vision** — resolved by the B1 gate; record the outcome + any fallback in the coordinator.
- **Q-verify-trigger** — auto-run verify+summarize on every PDF ingest vs. user-initiated. *Default:* auto
  fire-and-forget after chaptering (cost/speed not a constraint, Decision #2), with a manual re-run path.