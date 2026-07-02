# Source Chaptering — Track C: Surfaces (sections API + viewer TOC + interaction layer)

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared decisions,
> conventions, concurrency, file ownership — then execute this track's chunks here, one per session.
> **Location:** `.claude/plans/source-chaptering/c-surfaces.md` → archived with the directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** **Track A must be ☑** (needs `Source.get_sections` + the `source_section` model for the
endpoint). Check the coordinator's Global status table before starting.
**Concurrent with:** **Track B** — safe to run at the same time. C touches only `api/*` + `frontend/*`; B
touches backend domain/graph/commands/ai. No shared files.
**State at handoff (2026-06-22):** planning complete; no chunks started.
**Paste-able resume prompt (run in a fresh chat):**
> Continue Source-Chaptering Track C (Surfaces). Read `.claude/plans/source-chaptering/coordinator.md` then
> `.claude/plans/source-chaptering/c-surfaces.md` in full. Confirm Track A is ☑ in the coordinator. Implement
> the next unstarted chunk (one only), verify it (`npm run build` for frontend chunks), then update BOTH this
> file's Status table AND the coordinator's Global status table + Changelog, and tell me when it's safe to
> clear context.

## This track's file ownership
Creates/modifies: `api/routers/sources.py`, `api/models.py`, `frontend/src/lib/types/api.ts`,
`frontend/src/lib/api/sources.ts`, `frontend/src/components/source/SourceDetailContent.tsx`,
`frontend/src/app/(dashboard)/sources/[id]/page.tsx`, a new TOC component under
`frontend/src/components/source/`, `frontend/src/components/source/PassageSelectionMenu.tsx` (extend),
`frontend/src/lib/locales/*` (append-only keys).
**Do NOT touch** `open_notebook/domain/notebook.py`, `graphs/`, `commands/`, `ai/` (Track A/B own those) —
read the backend only through the API.

## Per-chunk workflow
read referenced files → implement → verify → mark ☑ here AND in the coordinator → note new Open Questions →
announce "✅ Chunk C.n complete — safe to clear context" → stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| C1 | `GET /sources/{id}/sections` + `SourceSectionResponse` + `has_sections` flag | ☐ todo | | needs A ☑ |
| C2 | Frontend types + API client (`getSections`) | ☐ todo | | |
| C3 | TOC sidebar + per-chapter rendering | ☐ todo | | |
| C4 | Interaction layer: selection actions + per-chapter AI actions + citation→jump | ☐ todo | | |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet.)_

## Chunks (verbatim)

### Chunk C1 — Sections API endpoint + schemas + flag
- **Goal:** Expose the chapter tree over REST and signal its presence on the source detail, without breaking
  existing endpoints.
- **Read first:** `api/routers/sources.py` `GET /sources/{id}` (572-632, response build); `api/models.py`
  `SourceResponse` (359-376), `SourceListResponse` (378-393), `AssetModel` (302-304); `api/main.py:303`
  (router registration); `Source.get_sections`/`get_outline` (Track A3) for the data shape.
- **Spec / exact values:** Decision #4. New `GET /sources/{source_id}/sections` →
  `SourceSectionResponse { id, title, has_sections, sections_count, sections: SourceSectionNode[] }` where
  `SourceSectionNode { id, title, level, order, page_start?, page_end?, summary?, content?, children: [] }`.
  Add `has_sections: bool` and `sections_count: int` to `SourceResponse` (and the list response if cheap).
- **Reuse:** the exact `@router.get(..., response_model=...)` + `Source.get(...)` + 404/500 handling pattern
  from the existing source handlers; routers are auto-included via `sources.router`.
- **Steps:** (1) add the two Pydantic models to `api/models.py`; (2) add the endpoint to
  `api/routers/sources.py` calling `Source.get_sections()`; (3) populate `has_sections`/`sections_count` in
  the `GET /sources/{id}` handler; (4) decide whether to return `content` inline or only via the section node
  (default: include `summary` always, `content` on request to keep the payload light).
- **Verify:** `GET /sources/{id}/sections` returns a nested tree for a chaptered PDF and
  `{has_sections:false, sections:[]}` for an unchaptered source; `/docs` lists it; existing source endpoints
  unchanged; `uv run pytest tests/test_models_api.py` green.

### Chunk C2 — Frontend types + API client
- **Goal:** Mirror the new contract in TypeScript and add the client call.
- **Read first:** `frontend/src/lib/types/api.ts` (21-46, `SourceListResponse`/`SourceDetailResponse`);
  `frontend/src/lib/api/sources.ts` (existing `get`/`list`/`downloadFile`).
- **Spec / exact values:** mirror C1 exactly — `SourceSectionNode` + `SourceSectionResponse`; add
  `has_sections?`/`sections_count?` to `SourceDetailResponse`.
- **Reuse:** the `apiClient.get<T>(path).then(r => r.data)` pattern.
- **Steps:** (1) add the types; (2) add `sourcesApi.getSections(id)`; (3) `npm run build` / `tsc`.
- **Verify:** `npm run build` passes; types match the backend field names exactly.

### Chunk C3 — TOC sidebar + per-chapter rendering
- **Goal:** Replace the single-blob render with a navigable chapter view: a TOC outline + one chapter rendered
  at a time, reusing the existing markdown renderer. Falls back to the flat `full_text` render when a source
  has no sections.
- **Read first:** `frontend/src/components/source/SourceDetailContent.tsx` (tabs 466-551; the `ReactMarkdown`
  block 523-548, `full_text` @546); `frontend/src/app/(dashboard)/sources/[id]/page.tsx` (27-76 layout).
- **Spec / exact values:** Decision #10 (render **cleaned** per-section content by default; raw stays via
  download; no raw/cleaned toggle in v1). TOC = sticky, click-to-jump, collapsible nesting by `level`.
- **Reuse:** the **existing** `ReactMarkdown` + `remarkGfm` + custom-components block — render each chapter
  through it, don't add a second renderer; existing `Tabs`/`Card` primitives; `data-section-id` anchors on
  heading components for scroll targets.
- **Steps:** (1) fetch `sourcesApi.getSections(id)` in the Content tab; (2) new
  `frontend/src/components/source/SourceTOC.tsx` rendering the tree; (3) render the active chapter's
  content via the existing markdown block (lazy-load chapter content if not inlined); (4) graceful fallback to
  the current `full_text` render when `!has_sections`; (5) locale keys for new labels.
- **Verify:** a chaptered textbook shows a TOC; clicking a chapter shows just that chapter and is readable;
  an unchaptered/instruction doc still renders as today; `npm run build` passes.

### Chunk C4 — Interaction layer: selection actions + per-chapter AI actions + citation→jump
- **Goal:** Make the document interactive — extend the existing selection gesture into an action menu, add
  per-chapter AI actions, and make citations jump to the right chapter.
- **Read first:** `frontend/src/components/source/PassageSelectionMenu.tsx` (LANDED — selection→"Chat about
  this" sub-chat); `frontend/src/components/source/MessageReferences.tsx` + `ChatPanel.handleReferenceClick`
  (`ChatPanel.tsx:160-171`, `openModal`); `frontend/src/lib/utils/source-references.tsx` (`#ref-{type}-{id}`
  scheme); the `SourceTOC`/anchors from C3.
- **Spec / exact values:** coordinator Decision #11 — **annotations/highlights are OUT** (deferred to
  pdf-viewer-citations Phase 4). In scope: (a) selection menu items **Explain / Ask / Save-note** (Ask reuses
  the existing sub-chat spawn); (b) per-chapter buttons **Summarize / Quiz** that send a scoped prompt to the
  chat; (c) citation click → scroll the viewer to the cited section via the `data-section-id` anchors.
- **Reuse:** `PassageSelectionMenu` (extend its item list — don't rebuild the gesture); the sub-chat spawn it
  already wires; `handleReferenceClick`/`openModal`; the note-create path; C3's anchors.
- **Steps:** (1) extend `PassageSelectionMenu` with Explain/Save-note actions alongside the existing
  "Chat about this"; (2) add per-chapter action buttons in `SourceTOC`/chapter header → dispatch a scoped chat
  message; (3) wire citation→section scroll (map citation `id`/`page` → `data-section-id`); (4) locale keys.
- **Verify:** selecting AI/source text shows the action menu; Explain/Ask/Save-note each work; a chapter's
  Summarize/Quiz button drives the chat; clicking a citation scrolls to the right chapter; annotations are
  absent (correctly deferred); `npm run build` passes.

## Open Questions (this track)
- **Q-section-content-payload** — return `content` inline in the sections endpoint vs. lazy per-chapter fetch.
  *Default:* `summary` always inline; `content` lazy to keep the tree light. Revisit if it adds a round-trip
  that hurts UX.
- **Q-quiz-scope** — "Quiz me" output format (inline chat vs. saved note). *Default:* inline chat message;
  promote to a note later if wanted.