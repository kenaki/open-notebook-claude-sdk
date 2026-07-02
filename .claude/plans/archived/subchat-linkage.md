> ⚠️ **SUPERSEDED 2026-06-22 — do not execute from this doc.** Folded into the merged master plan
> `.claude/plans/notebook-chat-workspace.md` (this doc's sub-chat + citation chunks became that plan's
> Chunks 2, 3, 9, 11). Kept for history only. Use the master plan.

# Sub-chats + Chat/Source Linkage + Structured Citations — Feature Development Doc

> **Living master plan & single source of truth.** Written so a fresh, uncontextualized session can
> pick up any unstarted chunk, execute it, verify it, and mark it done — without the original
> conversation. Keep the Status table + Changelog current.
> **Location:** `.claude/plans/subchat-linkage.md` while active → moved to
> `.claude/plans/archived/subchat-linkage.md` once every chunk is done.

---

## SESSION HANDOFF — resume here
**State at handoff (2026-06-21):** Planning complete. No code written yet. Branch
`claude-agent-integration`. All current-state findings verified against the codebase.
**To resume:** 1) read this whole file; 2) re-read the referenced files for the chunk you're doing;
3) do the next ☐ chunk in order — **one chunk per session**; 4) at the end: verify → update Status +
Changelog → announce "✅ Chunk X complete — safe to clear context" → stop.
**Paste-able resume prompt (run in a fresh chat):**
> Continue the sub-chat/linkage/citations feature. Read `.claude/plans/subchat-linkage.md` in full,
> then implement the next unstarted chunk (one only), verify it, update the doc's Status table +
> Changelog, and tell me when it's safe to clear context. If that was the last build-now chunk,
> archive the doc per its Completion section.

---

## How to use this document (read first, every session)
1. Decisions in the Decisions log are law. Never invent a value/requirement → add to Open Questions and ask.
2. **Reuse before create.** Smallest faithful diff. This codebase already has citation plumbing,
   session CRUD, and a markdown renderer — extend them, don't rebuild.
3. **Per-chunk workflow:** read referenced files → implement → verify → update Status + Changelog →
   note new Open Questions → **announce it's safe to clear context** → stop. **One chunk per session.**
4. Conventions: see "Conventions / translation notes" below before touching frontend or migrations.
5. **Coordinate with `.claude/plans/pdf-viewer-citations.md`** — its Phase 3 touches the same citation
   files (`source-references.tsx`, `prompts/chat/system.jinja`). See Reconciliation.

### Context-clear checkpoints (one chunk per session)
Every chunk is a checkpoint. At the end of each: (1) verify, (2) mark ☑ + Changelog line, (3) record
decisions/Open Questions, (4) tell the user "✅ Chunk X complete and verified — safe to clear context.
Next: Chunk Y." then **stop**. Don't roll into the next chunk in the same session unless asked.

### Completion & archival
When the **final build-now chunk (Chunk 4) is ☑ done**: append a Changelog line ("All chunks
complete — archived 2026-..."), then **move this file** to `.claude/plans/archived/subchat-linkage.md`
(`mkdir -p .claude/plans/archived && mv .claude/plans/subchat-linkage.md .claude/plans/archived/`),
and tell the user the plan is complete and archived.

### Status table
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| 0 | Backend foundation: persist `parent_session_id` + `quote`, migration, endpoints, prompt injection | ☐ todo | | No deps |
| 1 | Structured citations — backend (schema + resolver) | ☐ todo | | No deps (independent of 0) |
| 2 | Structured citations — frontend (types + CitationCard) | ☐ todo | | Needs Chunk 1 |
| 3 | Sub-chat plumbing — frontend (types/hooks/store) | ☐ todo | | Needs Chunk 0 |
| 4 | Sub-chat UX — selection capture, "Chat about this", side-sheet, quote banner | ☐ todo | | Needs Chunk 3 |
| 5 | Full dock / multi-panel side-by-side layout | ⊘ deferred | | Needs Chunk 4 |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

**Execution order:** 0 → 1 → 2 → 3 → 4. Two independent tracks exist (citations = 1,2; sub-chats =
0,3,4); linear order is the safe default. Chunk 1 may be done before 0 if preferred.

### Changelog
- _(none yet)_

---

## Context — why
Open Notebook migrated to the Claude Agent SDK (chat now optionally routes through the local Claude
CLI with in-process MCP tools that can read notebooks/sources/notes). On top of that, we want three
capabilities:
1. **Sub-chats** — highlight text in any AI reply, click "Chat about this", spawn a focused child
   chat seeded with the quoted passage and visually associated with its parent.
2. **Chat ↔ source linkage** — sub-chats carry a `parent_session_id`; the seeding `quote` is persisted
   and shown as a "DISCUSSING THIS PASSAGE" banner; citations resolve to real source material.
3. **Enriched responses** — replies return a structured `citations[]` array (id/type/number/title/
   snippet) plus `followups[]`, rendered as reference cards + suggested next questions instead of bare
   inline `[source:id]` text.

**Current state (verified 2026-06-21):**
- Sub-chats do **not** exist anywhere. Chat is two parallel systems: notebook-chat (multi-source,
  **non-streaming**, `POST /chat/execute`) and source-chat (per-source, **SSE streaming**). UI shows
  one chat at a time in a fixed 3-column flex layout (Sources | Notes | Chat); no resizable/dockable
  primitive and no library for one.
- `ChatSession` is a SurrealDB record (`chat_session` table, **SCHEMALESS**) linked to a notebook via
  a `refers_to` edge. **Messages live in a LangGraph SQLite checkpoint, not SurrealDB.**
- Citation plumbing already exists end-to-end: prompts emit `[source:id]`/`[note:id]`/`[insight:id]`;
  the frontend parses them into numbered clickable refs and opens modals. **The gap is enrichment
  (structured array, titles/snippets, followups), not basic plumbing.**

**Scope of THIS effort:** Chunks 0–4 (build now), on the **notebook-chat surface first**. Source-chat
parity and the full dock layout are deferred (see Deferred + Open Questions).

## Decisions log
| # | Question | Decision |
|--:|----------|----------|
| 1 | Where do sub-chats live? | **Hybrid.** Persist `parent_session_id` + `quote` as nullable fields on `ChatSession`. Keep `docked`/`width`/`draft`/`pending` client-only in Zustand. |
| 2 | Response enrichment richness? | **Structured citation schema** — `Citation{id,type,number,title,snippet}` + `followups[]` on the chat message response. |
| 3 | Sub-chat UX shape? | **Side-sheet MVP first.** Full side-by-side dock layout deferred (Chunk 5). |
| 4 | Which chat surface first? | **Notebook chat** (`/chat/execute`, non-streaming → simplest to return `citations[]` in one response). Source-chat (SSE) parity deferred — append citations as a final stream event later. *(Default; veto at review.)* |
| 5 | How are `followups[]` produced? | **Prompt-emit + parse.** Instruct the model (system prompt) to end with a machine-parseable follow-ups block; backend strips it from `content` into `followups[]`. Avoids an extra LLM call (bad on the Claude-agent subprocess path). *(Default; veto at review.)* |
| 6 | How are `citations[]` produced? | **Backend resolution of inline markers.** Keep the model emitting `[type:id]` markers (already enforced by prompts + MCP tools); backend parses them, dedups, numbers, and fetches `title`/`snippet` from SurrealDB. The model is NOT asked to emit structured JSON (fragile on the agent path). *(Default; veto at review.)* |

### Reconciliation — with `.claude/plans/pdf-viewer-citations.md`
That plan (active) overlaps on citation files. **Compose, do not overwrite:**
- Its Phase 3 extends the citation token to **`[source:<id>#p=<n>]`** (page anchor). Our Chunk 1
  resolver MUST tolerate the optional `#p=<n>` fragment, and our `Citation` schema MUST include an
  optional `page` field so the two features stack (a citation can carry both a snippet *and* a page).
- Its Phase 3 and our Chunks 1–2 both edit `prompts/chat/system.jinja` and
  `frontend/src/lib/utils/source-references.tsx`. Whoever lands second **merges**: keep both the
  numbered-card rendering (ours) and the page-jump click target (theirs).
- No code conflict today (that plan is "nothing built yet"). Re-check its Status before editing shared files.

## Conventions / translation notes
- **Migrations:** numbered pairs `N.surrealql` + `N_down.surrealql` under
  `open_notebook/database/migrations/`, hard-registered in `open_notebook/database/async_migrate.py`
  (`AsyncMigrationManager.__init__`, ~lines 98–123). Next number = **16**. `chat_session` is
  **SCHEMALESS**, so new fields auto-persist; the migration is for versioning/rollback (no `DEFINE
  FIELD` strictly required, but write `REMOVE FIELD IF EXISTS` in the down for symmetry).
- **Domain model nullable fields:** add field names to `nullable_fields: ClassVar[set[str]]` so `None`
  values persist (see `_prepare_save_data` in `domain/base.py`). Declare as `Optional[...] = None`.
- **Endpoint response mapping:** always use `getattr(session, "field", None)` when reading new fields
  off a session (defensive against old records) — matches existing `model_override` handling.
- **Frontend:** Next.js 16 / React 19 / TS / Zustand / TanStack Query. i18n — any new user-facing
  string needs translation keys (check how existing chat strings are keyed before hardcoding).
  API client base is `apiClient` in `src/lib/api/`; types in `src/lib/types/api.ts`.
- **Graph async bridging:** `call_model_with_messages` is a sync LangGraph node that bridges to async
  via a new event loop / ThreadPool — do not `await` directly in the node; follow the existing pattern.
- **Run from source** (not Docker) for the Claude-agent path; checkpoint at `./data/sqlite-db/`.

## Chunks

### Chunk 0 — Backend foundation: persist `parent_session_id` + `quote`, migration, endpoint threading, prompt injection
- **Goal:** A chat session can be created/read/updated with `parent_session_id` and `quote`, both
  persisted and returned by the API; when a session has a `quote`, it is injected into the chat
  system prompt so the model knows the seeding passage. Fully testable via API alone.
- **Read first:**
  - `open_notebook/domain/notebook.py` — `ChatSession` (~line 679: `table_name`, `nullable_fields`,
    `title`, `model_override`, `relate_to_notebook`, `relate_to_source`).
  - `open_notebook/database/migrations/15.surrealql` + `15_down.surrealql` (format example);
    `open_notebook/database/migrations/3.surrealql` (confirms `chat_session SCHEMALESS`).
  - `open_notebook/database/async_migrate.py` (~98–123, migration registration).
  - `api/routers/chat.py` — `CreateSessionRequest` (22), `UpdateSessionRequest` (30),
    `ChatSessionResponse` (44), `create_session` (137), `get_session` (175), `update_session` (250),
    `get_sessions` (96), `execute_chat` (330).
  - `open_notebook/graphs/chat.py` — `ThreadState` (26), `call_model_with_messages` (51, system
    prompt at 53), `execute_chat` state assembly (`api/routers/chat.py:368-373`).
  - `prompts/chat/system.jinja` (the chat system prompt).
- **Exact values:** new fields `parent_session_id: Optional[str] = None`, `quote: Optional[str] = None`.
  Migration number **16**.
- **Reuse:** `model_override` is the exact precedent — copy its pattern through every layer (model
  field, `nullable_fields`, request/response schemas, all 5 endpoint mappings via `getattr`).
- **Steps:**
  1. `ChatSession`: add `parent_session_id` + `quote` fields; add both to `nullable_fields`.
  2. Create `migrations/16.surrealql` (comment-documenting the two new schemaless fields) +
     `16_down.surrealql` (`REMOVE FIELD IF EXISTS parent_session_id/quote ON TABLE chat_session;`).
     Register both in `async_migrate.py`.
  3. `api/routers/chat.py`: add the two fields to `CreateSessionRequest`, `UpdateSessionRequest`,
     `ChatSessionResponse`. Thread them: `create_session` (set on `ChatSession(...)`), `update_session`
     (`if "parent_session_id"/"quote" in update_data`), and into the response objects of
     `create/get/update/get_sessions` (use `getattr`).
  4. `graphs/chat.py`: add `quote: Optional[str]` to `ThreadState`.
  5. `api/routers/chat.py` `execute_chat`: set `state_values["quote"] = getattr(session, "quote", None)`
     alongside the existing `state_values[...]` assignments (~370–373).
  6. `prompts/chat/system.jinja`: add a conditional block, e.g.
     `{% if quote %}\n# SEED PASSAGE\nThis chat was started from this passage; treat it as the focus:\n> {{ quote }}\n{% endif %}` — place near the top, after the role line.
- **Verify:** Run API (`uv run uvicorn api.main:app --port 5055`), check startup log shows migration
  16 applied. Via `/docs` or curl: `POST /chat/sessions` with `parent_session_id` + `quote` →
  confirm both echoed back; `GET /chat/sessions/{id}` → confirm persisted. `POST /chat/execute` on a
  quoted session → confirm a normal reply (and, with a debug log of `system_prompt`, that the SEED
  PASSAGE block rendered). `uv run pytest tests/test_domain.py` stays green.

### Chunk 1 — Structured citations (backend: schema + resolver)
- **Goal:** `POST /chat/execute` and `GET /chat/sessions/{id}` return each AI message with a
  `citations: list[Citation]` array (resolved from inline markers, with titles/snippets) and a
  `followups: list[str]` array (parsed from a model-emitted block), with the followups block stripped
  from `content`.
- **Read first:**
  - `api/routers/chat.py` — `ChatMessage` (37), message conversion in `get_session` (199–210) and
    `execute_chat` (395–405).
  - `frontend/src/lib/utils/source-references.tsx` — the **existing** regex/parse logic
    (`parseSourceReferences`, the `(source_insight|note|source):([a-zA-Z0-9_]+)` pattern, dedup +
    numbering in `convertReferencesToCompactMarkdown`). **Port this numbering logic to the backend** so
    front and back agree on `number`.
  - `open_notebook/domain/notebook.py` — `Source`, `Note`, `SourceInsight` getters (for title/snippet:
    `Source.get`, `Note.get`; insight title = type, snippet = truncated content). Confirm exact field
    names before use.
  - `prompts/chat/system.jinja` (where to add the followups instruction).
- **Exact values:** `Citation{ id: str; type: Literal["source","note","source_insight"]; number: int;
  title: Optional[str]; snippet: Optional[str]; page: Optional[int] = None }` (the `page` is the
  pdf-plan reconciliation hook). Followups block sentinel — choose a robust, unlikely-in-prose marker,
  e.g. lines after a literal `\n---FOLLOWUPS---\n`, one question per line.
- **Reuse:** existing marker regex (port, incl. optional `#p=<n>`); existing async-in-sync bridge if a
  DB fetch is needed during response shaping (or do the resolution in the async router functions —
  `execute_chat`/`get_session` are already `async`, so fetch titles/snippets there, NOT in the sync
  graph node).
- **Steps:**
  1. Add `Citation` model + `citations: list[Citation] = []` and `followups: list[str] = []` to
     `ChatMessage` in `api/routers/chat.py`.
  2. Write a resolver helper (e.g. `api/chat_service.py` or a new `_resolve_citations(content) ->
     (clean_content, citations, followups)`): regex-extract `[type:id]` markers (tolerate `#p=<n>`),
     dedup + number in first-appearance order, fetch `title`/`snippet` per id from the domain models,
     split off the `---FOLLOWUPS---` block.
  3. Call the resolver when converting AI messages in **both** `execute_chat` and `get_session`
     (human messages get empty arrays). Keep `content` = the cleaned text (followups removed; inline
     markers may stay for backward-compat rendering).
  4. `prompts/chat/system.jinja`: add instruction to (a) keep citing with `[type:id]` markers
     (already present) and (b) after the answer, output `---FOLLOWUPS---` then 2–3 short follow-up
     questions, one per line. Make it conditional/optional so short replies aren't forced.
- **Verify:** `POST /chat/execute` against a notebook with sources → response AI message has
  `citations[]` populated with real titles/snippets and `followups[]` with 2–3 questions; `content`
  no longer contains the `---FOLLOWUPS---` block. `GET` the session → same shape persists. Confirm
  graceful behavior when the model emits no markers/followups (empty arrays, no crash).

### Chunk 2 — Structured citations (frontend: types + CitationCard)
- **Goal:** AI replies render a numbered **reference card list** (title + snippet, clickable to the
  existing modal) and **suggested follow-up** chips, driven by the new `citations[]`/`followups[]`.
  Inline-marker parsing stays as a fallback when arrays are absent.
- **Read first:**
  - `frontend/src/lib/types/api.ts` — `NotebookChatMessage` (194), `SourceChatMessage` (147),
    `BaseChatSession` (133), `NotebookChatSession` (190).
  - `frontend/src/components/source/ChatPanel.tsx` — `AIMessageContent`, `LinkComponent`,
    `handleReferenceClick` (~88–99), the ReactMarkdown setup.
  - `frontend/src/lib/utils/source-references.tsx` — current parse/render + the `onReferenceClick`
    contract and `#ref-{type}-{id}` href scheme.
  - `frontend/src/lib/hooks/useNotebookChat.ts` — where messages are stored/shaped for render.
  - An existing card/badge component under `frontend/src/components/ui/` to match styling.
- **Exact values:** mirror the backend `Citation` shape in TS (`id,type,number,title?,snippet?,page?`).
- **Reuse:** keep `handleReferenceClick(type,id)` → `openModal(...)` (unchanged); the CitationCard's
  click reuses it. Keep the existing markdown renderer for `content`.
- **Steps:**
  1. `api.ts`: add `Citation` interface; add `citations?: Citation[]` and `followups?: string[]` to
     `NotebookChatMessage` (and `SourceChatMessage` for later parity).
  2. New `CitationCard` (or `MessageReferences`) component: render the numbered list under an AI
     message; each row shows `number`, `title`, `snippet`; onClick → `handleReferenceClick(type,id)`.
  3. New follow-up chips row: render `followups[]` as clickable chips that prefill/send the chat input.
  4. Wire into `ChatPanel`'s AI message render: if `citations?.length` use the card list; else fall
     back to the existing inline parser. Ensure `useNotebookChat` carries the new fields through.
  5. Add i18n keys for any new static labels ("References", "Suggested follow-ups").
- **Verify:** Run frontend (`npm run dev` in `frontend/`), open a notebook, send a chat that cites
  sources → reference cards appear with titles/snippets, clicking opens the right modal; follow-up
  chips appear and clicking one sends that question. Old sessions (no arrays) still render via inline
  fallback. `npm run build` / typecheck passes.

### Chunk 3 — Sub-chat plumbing (frontend: types/hooks/store)
- **Goal:** The frontend can create a sub-chat (a session with `parent_session_id` + `quote`) and
  track open sub-chats in client-only view state. No selection UI yet — verified programmatically.
- **Read first:**
  - `frontend/src/lib/types/api.ts` — `CreateNotebookChatSessionRequest` (205),
    `NotebookChatSession` (190).
  - `frontend/src/lib/api/chat.ts` — `chatApi.createSession` (23), `getSessions`, `getSession`.
  - `frontend/src/lib/hooks/useNotebookChat.ts` — session create/switch logic, `currentSessionId`.
  - `frontend/src/lib/stores/notebook-columns-store.ts` (Zustand pattern to mirror).
- **Exact values:** add `parent_session_id?: string`, `quote?: string` to
  `CreateNotebookChatSessionRequest` and to `NotebookChatSession` / `BaseChatSession`.
- **Reuse:** `chatApi.createSession` already POSTs the request body straight through — adding fields to
  the request type is sufficient (no client change beyond types). Mirror `notebook-columns-store` for
  the new store.
- **Steps:**
  1. `api.ts`: add the two fields to the request + session types (back-end already accepts/returns
     them from Chunk 0).
  2. `useNotebookChat`: add `createSubChat(parentSessionId, quote, title?)` that calls
     `chatApi.createSession({ notebook_id, parent_session_id, quote, title })` and returns the new
     session; expose a derived `childSessionsOf(parentId)` selector from the loaded session list.
  3. New client-only Zustand store (e.g. `sub-chat-store.ts`): tracks open sub-chat panel ids +
     active one (and reserves `docked`/`width`/`draft` for later — client-only, never sent to API).
- **Verify:** Temporarily call `createSubChat` (or via React Query devtools / a throwaway button);
  confirm a session is created with `parent_session_id` + `quote` persisted (check `GET
  /chat/sessions/{id}`), and `childSessionsOf` returns it. Typecheck/build passes.

### Chunk 4 — Sub-chat UX: selection capture, "Chat about this", side-sheet, quote banner
- **Goal:** Highlight text in any notebook-chat AI reply → a floating "Chat about this" button →
  click spawns a sub-chat seeded with the quote, opening in a **side-sheet** that shows a "DISCUSSING
  THIS PASSAGE" banner and a focused empty-state; the parent chat shows its sub-chats (derived from
  `parent_session_id`).
- **Read first:**
  - `frontend/src/components/source/ChatPanel.tsx` — AI message body rendering (where to attach a
    `mouseup`/selection handler and `data-chat-scope`).
  - `frontend/src/lib/hooks/useNotebookChat.ts` (now with `createSubChat` from Chunk 3) +
    `sub-chat-store.ts`.
  - `frontend/src/components/ui/` — an existing sheet/drawer/dialog primitive (Radix-based) to host
    the side-sheet; confirm one exists before adding a dep.
  - `frontend/src/app/(dashboard)/notebooks/[id]/page.tsx` — the 3-column layout (where the side-sheet
    mounts).
- **Exact values:** "Chat about this" button label; banner heading "DISCUSSING THIS PASSAGE";
  empty-state copy "Ask anything about this passage." (all via i18n keys). Selection must be
  non-trivial (e.g. trimmed length ≥ a small threshold) before showing the button.
- **Reuse:** existing sheet/dialog primitive for the side-sheet; the existing `ChatPanel` for the
  sub-chat body (a sub-chat is just a chat with a banner) — render `ChatPanel` inside the sheet keyed
  to the sub-chat session.
- **Steps:**
  1. Add a `mouseup` handler on AI message bodies that reads `window.getSelection()`, captures text +
     caret rect + the originating session id (walk up to `[data-chat-scope]`); store in local state.
  2. Render a floating "Chat about this" button at the caret rect when a valid selection exists.
  3. On click: `createSubChat(parentSessionId, selectedText)` → open the side-sheet for the new
     session (store in `sub-chat-store`), clear the selection, focus the input.
  4. Side-sheet: render the quote banner (from `session.quote`) + the focused empty-state + a
     `ChatPanel` bound to the sub-chat session.
  5. In the parent chat header/sidebar, show a small "sub-chats" affordance listing
     `childSessionsOf(parentId)`; clicking reopens that sub-chat's side-sheet.
- **Verify:** Run frontend; in a notebook chat, select text in an AI reply → button appears at the
  selection → click → side-sheet opens with the "DISCUSSING THIS PASSAGE" banner showing the exact
  quote and the focused empty-state; send a message in the sub-chat and get a reply; reload → the
  sub-chat still exists (persisted) and is listed under its parent. Typecheck/build passes.
- **On completion:** this is the final build-now chunk → perform archival (see Completion & archival).

### Deferred (documented, not built now)
- **Chunk 5 — Full dock / multi-panel side-by-side layout** ⊘
  Replace the side-sheet with true side-by-side panels: parent chat then its children to the right,
  recursive nesting, dock/pop, resizable widths, derived CSS `order`. **Needs:** Chunk 4; a
  resizable-panel dependency (`react-resizable-panels` or `re-resizable` — none present today); a
  multi-session layout engine; reworking the hardcoded `flex-1` chat column and the
  `notebook-columns-store`. Largest, frontend-heavy; do only if the side-sheet proves insufficient.
- **Source-chat parity** ⊘ for citations + sub-chats: the source-chat path is **SSE streaming**, so
  `citations[]`/`followups[]` must be emitted as a final stream event and sub-chat creation wired into
  `useSourceChat`. Apply the same patterns once the notebook-chat versions are proven.
- **Message-precise back-navigation** ⊘: anchoring a sub-chat to the exact parent *message* (scroll +
  highlight). Needs a stable AI-message id — today `AIMessage(content=text)` has none
  (`claude_agent.py:181`) and the API falls back to a positional `msg_{len}` id (`chat.py:205`/`400`).
  Cheap fix when wanted: assign `id=str(uuid4())` at `AIMessage` construction. Not required for the
  hybrid design (anchor is the persisted `quote` text + `parent_session_id`).

## Verification (end-to-end)
- **Backend:** `uv run uvicorn api.main:app --port 5055` boots, migration 16 logged once; `uv run
  pytest tests/test_domain.py tests/test_graphs.py` green. Manual via `/docs`: create sub-chat session
  (parent + quote) → execute → response carries `citations[]` + `followups[]`; clean `content`.
- **Frontend:** `cd frontend && npm run build` (typecheck) passes. Manual: cards + follow-up chips
  render and are clickable; select-text → "Chat about this" → side-sheet sub-chat with quote banner;
  sub-chat persists across reload and is listed under its parent.
- **Known baseline noise to ignore:** pre-existing lint warnings unrelated to touched files; the
  positional message-id fallback (deferred); Docker-only checkpoint path differences (run from source).

## Open Questions (surface to human; don't guess)
- **Q-surface** — Build on notebook-chat only, or source-chat too? *Default: notebook-chat first;
  source-chat parity deferred (Decision 4).* Veto if source-chat is needed in v1.
- **Q-followups** — Prompt-emit + parse vs. a dedicated generation call? *Default: prompt-emit + parse
  (Decision 5).* Revisit if followups quality is poor on the Claude-agent path.
- **Q-snippet** — Snippet source for a citation: first N chars of the cited record, or the specific
  passage the model used? *Default: truncated record content (title + first ~200 chars)*; passage-level
  snippets need the model to emit offsets (out of scope; relates to pdf-plan provenance).
- **Q-pdfcoord** — Confirm with the maintainer of `pdf-viewer-citations.md` that the `Citation.page`
  field + `#p=<n>` marker tolerance is the agreed integration seam before both touch shared files.

## Reference index
- **Files touched (build-now):**
  - Backend: `open_notebook/domain/notebook.py`, `open_notebook/database/migrations/16.surrealql`(+`_down`),
    `open_notebook/database/async_migrate.py`, `api/routers/chat.py`, `open_notebook/graphs/chat.py`,
    `prompts/chat/system.jinja`, (maybe) `api/chat_service.py`.
  - Frontend: `frontend/src/lib/types/api.ts`, `frontend/src/lib/api/chat.ts`,
    `frontend/src/lib/hooks/useNotebookChat.ts`, `frontend/src/lib/utils/source-references.tsx`,
    `frontend/src/components/source/ChatPanel.tsx`, new `CitationCard`/`MessageReferences` component,
    new `sub-chat-store.ts`, `frontend/src/app/(dashboard)/notebooks/[id]/page.tsx`, i18n locale files.
- **Primitives to reuse:** `model_override` end-to-end pattern (precedent for new session fields);
  `nullable_fields`/`_prepare_save_data` (`domain/base.py`); migration pair format (`migrations/15.*`);
  inline marker regex + numbering (`source-references.tsx`); `handleReferenceClick`→`openModal`
  contract; `notebook-columns-store` (Zustand pattern); existing Radix sheet/dialog primitive.
- **Deps available:** ReactMarkdown (+remark-gfm/math, rehype-katex), Zustand, TanStack Query, Radix
  UI. **Not present:** any resizable/dockable panel lib (needed only for deferred Chunk 5).

### Post-exploration refinements (confirmed APIs, 2026-06-21)
- `ChatSession(ObjectModel)` @ `domain/notebook.py:679` — `table_name="chat_session"`,
  `nullable_fields={"model_override"}`, fields `title`, `model_override`; `relate_to_notebook`/
  `relate_to_source` use `self.relate("refers_to", id)`.
- `api/routers/chat.py`: `CreateSessionRequest`@22, `UpdateSessionRequest`@30, `ChatMessage`@37,
  `ChatSessionResponse`@44, `ExecuteChatRequest`@64, `ExecuteChatResponse`@75; `get_sessions`@96,
  `create_session`@137, `get_session`@175, `update_session`@250, `execute_chat`@330 (state assembly
  370–373, message conversion 395–405). Message id today: `getattr(msg,"id",f"msg_{len(messages)}")`.
- `graphs/chat.py`: `ThreadState`@26, `_generate_ai_message`@34 (routes to Claude agent vs Esperanto),
  `call_model_with_messages`@51 (system prompt `Prompter("chat/system").render(data=state)`@53),
  graph compiled with `SqliteSaver`@108.
- `claude_agent.py`: `generate_with_claude_agent`@158 returns `AIMessage(content=text)`@181 (no id).
- Frontend: types `api.ts` (`BaseChatSession`@133, `SourceChatMessage`@147, `NotebookChatSession`@190,
  `NotebookChatMessage`@194, `CreateNotebookChatSessionRequest`@205); `chatApi`@`api/chat.ts:13`
  (`createSession`@23 POSTs body through); hooks `useNotebookChat.ts`, `useSourceChat.ts`; citation
  parsing `source-references.tsx` (used by `ChatPanel.tsx`, `search/StreamingResponse.tsx`).
- `chat_session` table is **SCHEMALESS** (`migrations/3.surrealql`). Migrations registered in
  `async_migrate.py` (~98–123). Latest migration is 15 → next is **16**.
