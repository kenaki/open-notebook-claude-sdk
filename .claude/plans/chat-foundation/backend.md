# Chat Foundation — Backend chunk specs (B1–B6)

> Chunk detail for the backend lanes. Read `coordinator.md` first (frozen contracts, decisions,
> reference index, conventions). Each chunk is handed to one worktree subagent by the orchestrator.
> After integrating any backend chunk: `systemctl --user restart on-api` before DB-dependent verifies.

---

## B1 — MIG: Migration 18 (all 3 schema changes) + register
- **Owns:** `open_notebook/database/migrations/18.surrealql` (NEW), `18_down.surrealql` (NEW),
  `open_notebook/database/async_migrate.py`. **Deps:** none.
- **Goal:** One migration carrying all three independent schema changes (frozen contract #1–#4), and
  register it in the explicit up/down lists.
- **Read first:** `migrations/17.surrealql` + `17_down.surrealql` (format + flexible-object idiom);
  `migrations/1.surrealql:44-52` (notebook SCHEMAFULL, `archived option<bool> DEFAULT False` :47);
  `async_migrate.py:96-183` (up list ends at 17 ~:127-129; `from_file` entries ~:165-180; down ~:182).
- **Spec — `18.surrealql`:**
  ```surql
  -- Migration 18: chat foundation (per-chat-context + auto-illustrate).
  -- chat_session & notebook are SCHEMAFULL → undeclared fields are dropped on save.
  -- (a) Per-chat context selection (NONE = inherit notebook's global drawer selection).
  DEFINE FIELD IF NOT EXISTS context_config ON TABLE chat_session FLEXIBLE TYPE option<object> DEFAULT NONE;
  -- (b) Per-notebook auto-illustrate toggle (default ON).
  DEFINE FIELD IF NOT EXISTS auto_illustrate ON TABLE notebook TYPE option<bool> DEFAULT true;
  -- (c) Sidecar for late-arriving chat illustration, keyed by the stable AI message id.
  DEFINE TABLE IF NOT EXISTS chat_message_media SCHEMAFULL;
  DEFINE FIELD IF NOT EXISTS message_id ON TABLE chat_message_media TYPE string;
  DEFINE FIELD IF NOT EXISTS session_id ON TABLE chat_message_media TYPE string;
  DEFINE FIELD IF NOT EXISTS mode       ON TABLE chat_message_media TYPE string; -- 'image'|'diagram'|'none'
  DEFINE FIELD IF NOT EXISTS media      ON TABLE chat_message_media FLEXIBLE TYPE option<object>;
  DEFINE FIELD IF NOT EXISTS diagram    ON TABLE chat_message_media TYPE option<string>;
  DEFINE FIELD IF NOT EXISTS created    ON chat_message_media DEFAULT time::now() VALUE $before OR time::now();
  DEFINE INDEX IF NOT EXISTS chat_message_media_message_id ON TABLE chat_message_media COLUMNS message_id UNIQUE;
  ```
- **Spec — `18_down.surrealql`:**
  ```surql
  -- Rollback migration 18
  REMOVE INDEX IF EXISTS chat_message_media_message_id ON TABLE chat_message_media;
  REMOVE TABLE IF EXISTS chat_message_media;
  REMOVE FIELD IF EXISTS auto_illustrate ON TABLE notebook;
  REMOVE FIELD IF EXISTS context_config ON TABLE chat_session;
  ```
  (Confirm `REMOVE … IF EXISTS` against existing `*_down.surrealql`; if the repo's down-migrations use a
  different style, mirror that — Q-A-downsyntax.)
- **Steps:** write both files; append `AsyncMigration.from_file(".../18.surrealql")` to the up list after
  the 17 entry and `.../18_down.surrealql` to the down list (mirror the existing multi-line `from_file`
  formatting).
- **Verify:** restart `on-api`; `journalctl --user -u on-api` shows "Migration successful. New version: 18"
  with no schema error. Existing sessions/notebooks still read back (context_config null, auto_illustrate
  true). `chat_message_media` table exists.

## B2 — MODELS: domain models (one file, all three additions)
- **Owns:** `open_notebook/domain/notebook.py`. **Deps:** B1.
- **Goal:** Add the `ChatMessageMedia` model, `Notebook.auto_illustrate`, and `ChatSession.context_config`
  — all three in one pass over the file that both features share.
- **Read first:** `domain/notebook.py:16-24` (`Notebook`), `:683-696` (`ChatSession` + `nullable_fields`);
  `domain/base.py:31-237` (base, `_prepare_save_data`, `nullable_fields`).
- **Spec:**
  - `Notebook.auto_illustrate: Optional[bool] = True` (added to `Notebook`, :16-24).
  - `ChatSession`: add field `context_config: Optional[dict] = None` (alongside `quote`/`tags`); add
    `"context_config"` to `nullable_fields` (currently `{"model_override","parent_session_id","quote"}`).
  - New `ChatMessageMedia(ObjectModel)` in the same file: `table_name="chat_message_media"`; fields
    `message_id: str`, `session_id: str`, `mode: str`, `media: Optional[dict] = None`,
    `diagram: Optional[str] = None`; `nullable_fields = {"media","diagram"}`. Add classmethods
    `get_for_session(session_id) -> list` and `get_for_message(message_id) -> Optional[ChatMessageMedia]`
    via `repo_query`. (Ensure `Optional`/`dict` imports present.)
- **Verify:** `uv run python -c "from open_notebook.domain.notebook import Notebook, ChatSession, ChatMessageMedia"`.
  With B1 applied: create `ChatMessageMedia(message_id='t1', session_id='s1', mode='none')`, `await .save()`,
  `await ChatMessageMedia.get_for_message('t1')` returns it. Fetch a notebook → `.auto_illustrate is True`.
  `uv run pytest tests/test_domain.py`.

## B3 — MSGID: stable AIMessage id
- **Owns:** `open_notebook/graphs/chat.py`. **Deps:** none.
- **Goal:** Every AI message carries a deterministic stable `.id` persisting through the checkpoint so
  the enrichment job can correlate back to it. The consumer is the W1 trigger in
  `chat_completion_command`, which reads the id **in-process** from the graph invoke result (frozen
  contract #5/#6 v2 — there is no API response field for this; the old `illustration_job_id` plan is dead).
- **Read first:** `graphs/chat.py:137-185` (the `call_model_with_messages` node, AIMessage return :178-180).
- **Spec:** at `graphs/chat.py:178`, extend the existing `model_copy` to assign an id only if absent:
  `cleaned_message = ai_message.model_copy(update={"content": cleaned_content, "id": ai_message.id or f"ai-{uuid4().hex}"})`.
  `from uuid import uuid4` at the top. Never overwrite an existing id.
- **Verify:** `uv run python -c "import open_notebook.graphs.chat"`. Send a chat message; the AI message has
  an `id` like `ai-…` (not `msg_0`); re-fetch `GET /chat/sessions/{id}` → **same** id (proves checkpoint
  persistence).

## B4 — CTX-CRUD: `context_config` on session schemas + handlers
- **Owns:** `api/routers/chat/schemas.py` (session schema classes `CreateSessionRequest`/`UpdateSessionRequest`/
  `ChatSessionResponse` :6,23,96) + `api/routers/chat/sessions.py` (all session handlers: `get_sessions` :26,
  `create_session` :59, `get_session` :94, `update_session` :133). **Deps:** B2.
  > B4 and B5 now edit **different files** in the `api/routers/chat/` package — no per-function worktree
  > isolation required for file conflicts; standard worktree isolation still applies for clean integration.
- **Goal:** Surface `context_config` through session create/update/read, stored verbatim (no backend
  interpretation). `null` = inherit; object = own selection; explicit `null` clears (reset-to-default).
- **Read first:** coordinator frozen-contract #2; `api/routers/chat/schemas.py:6-96` (session schemas);
  `api/routers/chat/sessions.py:26-169` (all session handlers).
- **Spec:**
  - Add `context_config: Optional[Dict[str, Any]] = Field(None, description="Per-chat source/note context selection; null = inherit notebook default")`
    to `CreateSessionRequest`, `UpdateSessionRequest`, `ChatSessionResponse` (`Dict`/`Any`/`Optional`
    already imported).
  - `create_session`: pass `context_config=request.context_config` into `ChatSession(...)`; include
    `context_config=session.context_config` in the returned response.
  - `update_session`: after the existing per-key blocks add
    `if "context_config" in update_data: session.context_config = update_data["context_config"]`
    (the `model_dump(exclude_unset=True)` idiom means explicit `null` clears it). Add
    `context_config=getattr(session, "context_config", None)` to the returned response.
  - `get_sessions` + `get_session` response builders: add `context_config=getattr(session, "context_config", None)`.
- **Verify:** imports clean; round-trip via `http://localhost:5055/docs`: `POST /chat/sessions` with
  `context_config={"sources":{},"notes":{}}` → `GET` returns it; `PUT` to `null` clears; `PUT` a populated
  map persists. `uv run pytest tests/test_domain.py`.

## B5 — HYDRATE: sidecar merge into session reads *(revised 2026-07-02 — contract #6 v2)*
- **Owns:** `api/routers/chat/citations.py` (`_build_chat_message` :105) **only**. **Deps:** B2, B3.
  > v2 scope cut: NO `execute.py` or `schemas.py` edits. `/chat/execute` is a 202 submit that returns no
  > messages (bg A2), so the ONLY message read path is `GET /chat/sessions/{id}` → `sessions.py:109` →
  > `_build_chat_message` (citations.py). The old `ExecuteChatResponse.illustration_job_id` field is
  > DROPPED (see coordinator P-5). The trigger is W1's job (`commands/chat_commands.py`), not B5's.
- **Goal:** Merge `chat_message_media` sidecar rows into messages at read time so a late-arriving
  illustration hydrates into the session response (single source of truth, P-4).
- **Read first:** `api/routers/chat/citations.py:105` (`_build_chat_message` — already `async`, called
  per-message from `sessions.py:109`); coordinator P-3 + frozen contract #4.
- **Spec:**
  - Inside `_build_chat_message`, for AI messages with a stable `.id` (`ai-…`): look up
    `await ChatMessageMedia.get_for_message(msg.id)` (UNIQUE index on `message_id` — a per-message
    point read; fine for local SurrealDB at chat-session scale, and it avoids touching B4's
    `sessions.py`. Revisit batching only if profiling ever says so).
  - Per row: `mode=='image'` and `media` → append `MediaItem(**row.media)` to `.media`;
    `mode=='diagram'` and `diagram` → append `f"\n\n```mermaid\n{row.diagram}\n```"` to `content`
    **after** `_resolve_citations` (don't disturb citation parsing); `mode=='none'` → nothing.
  - Failures in the lookup/merge must degrade to the un-hydrated message (log, never 500 a session read).
- **Verify:** insert a `chat_message_media` row (`mode='diagram', diagram='graph TD; A-->B'`) for a real AI
  message id → `GET /chat/sessions/{id}` shows a ` ```mermaid ` block in content. Insert an `image` row →
  `.media` gains the item. A session with NO sidecar rows reads back unchanged. `uv run pytest tests/`.

## B6 — NB-API: `auto_illustrate` passthrough on notebook-update
- **Owns:** `api/routers/notebooks.py`, `api/models.py`. **Deps:** B2.
- **Goal:** Let the notebook-update endpoint accept `auto_illustrate` so the F6 toggle can persist it.
- **Read first:** `api/routers/notebooks.py` (the update endpoint + its request schema — find where
  `chat_tag_colors`/`archived` are accepted) and `api/models.py` (the notebook update model).
- **Spec:** add `auto_illustrate: Optional[bool] = None` to the notebook update request schema and pass it
  through to the notebook save, mirroring how `chat_tag_colors`/`archived` flow through.
- **Verify:** `PUT`/update a notebook with `auto_illustrate:false` → persists across reload. With it false,
  a chat turn submits NO `illustrate_message` job (check `GET /commands/jobs` after a turn — cross-check
  once W1 is integrated; the trigger reads this flag).

## Open Questions (backend)
- **Q-A-downsyntax** — `18_down.surrealql` `REMOVE`/redefine style. *Default: match existing down files.*
- ~~**Q-A-getsession**~~ — RESOLVED 2026-07-02: there is only one message read path post-202
  (`GET /chat/sessions/{id}` → `_build_chat_message`); the hydrate lives inside it (B5 v2).
