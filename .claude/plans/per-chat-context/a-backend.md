# Per-Chat Context for Side Chats — Track A: Backend

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared
> decisions, conventions, the `context_config` shape, file ownership — then execute this track's chunk
> here. You should never need to open `b-frontend.md`.
> **Location:** `.claude/plans/per-chat-context/a-backend.md` → archived with the directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** none — runnable now.
**Concurrent with:** Track B (frontend) — fully file-disjoint, run both at once in separate chats.
**State at handoff (2026-06-23):** planning complete; no code written.
**Paste-able resume prompt (run in a fresh chat):**
> Continue Per-Chat Context Track A (Backend). Read `.claude/plans/per-chat-context/coordinator.md`
> then `.claude/plans/per-chat-context/a-backend.md` in full. Implement the next unstarted chunk (one
> only), verify it, then update BOTH this file's Status table AND the coordinator's Global status table
> + Changelog, and tell me when it's safe to clear context. If that was the last chunk of the last
> track, archive the feature directory per the coordinator's Completion section.

## This track's file ownership
Files this track creates/modifies (disjoint from Track B):
- `open_notebook/database/migrations/18.surrealql` (NEW)
- `open_notebook/database/migrations/18_down.surrealql` (NEW)
- `open_notebook/database/async_migrate.py`
- `open_notebook/domain/notebook.py`
- `api/routers/chat.py`
Shared files I must NOT touch: none (Track B is frontend-only).

## Per-chunk workflow
read referenced files → implement → verify → mark ☑ in this file AND the coordinator → note new Open
Questions → announce "✅ Chunk A1 complete — safe to clear context" → stop.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| A1 | Persist `context_config` on chat sessions (migration + model + API) | ☐ todo | | |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet)_

## Chunks (verbatim)

### Chunk A1 — Persist `context_config` on chat sessions (migration + model + API)
- **Goal:** Add a nullable `context_config` object to the `chat_session` record and surface it through
  the session create / update / read API, stored verbatim as an opaque object. `null` = inherit
  (default for existing + main chats); an object = a chat's own selection. No interpretation of the
  object on the backend.
- **Read first:**
  - `open_notebook/database/migrations/17.surrealql` (flexible-object field pattern)
  - `open_notebook/database/async_migrate.py` (lines ~95-200 — up/down lists; up ends at 17 ~line 127-129)
  - `open_notebook/domain/notebook.py:683-696` (`ChatSession` model + `nullable_fields`)
  - `api/routers/chat.py:33-143` (schemas), `:337-349`, `:372-396`, `:457-469`, `:491-528` (handlers/builders)
- **Spec / exact values:** see coordinator → Conventions (`context_config` JSON shape) + Decisions.
  Field is **nullable** (absent/`null` = inherit). The object is stored opaquely.
- **Reuse:** migration 17's `DEFINE FIELD IF NOT EXISTS … FLEXIBLE TYPE object …` idiom; the existing
  `model_dump(exclude_unset=True)` + per-key apply idiom in `update_session`.
- **Steps:**
  1. **`open_notebook/database/migrations/18.surrealql`** (NEW):
     ```surql
     -- Migration 18: per-chat context selection on chat sessions.
     -- chat_session is SCHEMAFULL, so an undeclared field is dropped on save.
     -- option<object> lets a session carry its own { sources, notes } context map,
     -- or NONE to inherit the notebook's global drawer selection.
     DEFINE FIELD IF NOT EXISTS context_config ON TABLE chat_session FLEXIBLE TYPE option<object> DEFAULT NONE;
     ```
  2. **`open_notebook/database/migrations/18_down.surrealql`** (NEW):
     ```surql
     REMOVE FIELD IF EXISTS context_config ON TABLE chat_session;
     ```
  3. **`open_notebook/database/async_migrate.py`:** append
     `AsyncMigration.from_file("open_notebook/database/migrations/18.surrealql")` to the up list
     (after the 17 entry ~line 127-129) and the matching `18_down.surrealql` to the down list (mirror
     position). Match the existing multi-line `AsyncMigration.from_file(...)` formatting.
  4. **`open_notebook/domain/notebook.py` (`ChatSession`):** add `"context_config"` to
     `nullable_fields`, and add field `context_config: Optional[dict] = None` alongside `quote`/`tags`.
     (Ensure `Optional`/`dict` typing imports already present — `Optional` is used in the class.)
  5. **`api/routers/chat.py` schemas:** add
     `context_config: Optional[Dict[str, Any]] = Field(None, description="Per-chat source/note context selection; null = inherit notebook default")`
     to **`CreateSessionRequest`**, **`UpdateSessionRequest`**, and **`ChatSessionResponse`**
     (`Dict`, `Any`, `Optional` are already imported in this module).
  6. **`api/routers/chat.py` `create_session` (372-396):** pass `context_config=request.context_config`
     into the `ChatSession(...)` constructor; include `context_config=session.context_config` in the
     returned `ChatSessionResponse`.
  7. **`api/routers/chat.py` `update_session` (491-528):** after the existing per-key blocks add
     ```python
     if "context_config" in update_data:
         session.context_config = update_data["context_config"]
     ```
     (the `exclude_unset=True` dump means sending `null` explicitly clears it → "reset to default"),
     and add `context_config=getattr(session, "context_config", None)` to the returned response.
  8. **`api/routers/chat.py` response builders:** add
     `context_config=getattr(session, "context_config", None)` to the `ChatSessionResponse` built in
     `get_sessions` (337-349) and the `ChatSessionWithMessagesResponse` built in `get_session`
     (457-469).
- **Verify:**
  - `uv run python -c "import api.routers.chat, open_notebook.domain.notebook, open_notebook.database.async_migrate"` (imports clean).
  - Restart the API (`systemctl --user restart on-api`; see memory) and confirm logs show migration 18
    runs once with no schema error; existing sessions read back with `context_config = null`.
  - Round-trip: `POST /chat/sessions` with `context_config={"sources":{},"notes":{}}` then
    `GET /chat/sessions/{id}` returns it; `PUT` it to `null` and confirm it clears; `PUT` a populated
    map and confirm it persists (via `http://localhost:5055/docs`).
  - `uv run pytest tests/test_domain.py` (ChatSession still constructs/saves cleanly).

## Open Questions (this track)
- _(none — the object is stored opaquely; all interpretation is frontend-side.)_
