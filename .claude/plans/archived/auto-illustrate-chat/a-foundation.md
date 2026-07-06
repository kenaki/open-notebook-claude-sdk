# Auto-Illustrate AI Chat — Track A: Foundation (data model + contracts)

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared
> decisions, conventions, concurrency, file ownership, the data contract — then execute this track's
> chunks here, one per session. You should never need to open another track's file.
> **Location:** `.claude/plans/auto-illustrate-chat/a-foundation.md` → archived with the directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** none — this is the head of the critical path. Start immediately.
**Concurrent with:** Track S (spikes — scratch only). **Blocks:** Tracks B and C cannot start until A is ☑.
**State at handoff (2026-06-23):** planning complete; no code written.
**Paste-able resume prompt (run in a fresh chat):**
> Continue auto-illustrate-chat Track A (Foundation). Read `.claude/plans/auto-illustrate-chat/coordinator.md`
> then `.claude/plans/auto-illustrate-chat/a-foundation.md` in full. Implement the next unstarted chunk
> (one only), verify it, then update BOTH this file's Status table AND the coordinator's Global status
> table + Changelog, and tell me when it's safe to clear context. After A3, announce that Tracks B and C
> are now unblocked. If that was the last chunk of the last track, archive the feature directory per the
> coordinator's Completion section.

## This track's file ownership
Files this track creates/modifies (frozen for A's duration; B & C never touch them):
- `open_notebook/graphs/chat.py` — stable AIMessage id
- `api/routers/chat.py` — hydrate-merge, `illustration_job_id`, job submission
- `open_notebook/domain/notebook.py` — `ChatMessageMedia` model + `Notebook.auto_illustrate` field
- `open_notebook/database/migrations/18.surrealql` (+ `18_down.surrealql`) — NEW
- `open_notebook/database/async_migrate.py` — register migration 18
- `api/routers/notebooks.py` and/or `api/models.py` — `auto_illustrate` on the notebook update schema/passthrough
Shared files I must NOT touch out of turn: none (A owns all foundation files; B/C run after A ☑).

## Per-chunk workflow
read referenced files → implement → verify → mark ☑ in this file AND the coordinator → note new Open
Questions → announce "✅ Chunk A.n complete — safe to clear context" → stop. One chunk per session.
After backend changes: `systemctl --user restart on-api` (and `on-worker` if commands changed) to apply.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| A1 | Stable AIMessage id + `illustration_job_id` on response | ☐ todo | | |
| A2 | Migration 18 + `ChatMessageMedia` model + `Notebook.auto_illustrate` | ☐ todo | | |
| A3 | Hydrate-merge sidecar + submit enrichment job + notebook-update passthrough | ☐ todo | | unblocks B & C |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet)_

## Chunks (verbatim — do not require another track file)

### Chunk A1 — Stable AIMessage id + response contract
- **Goal:** Every AI message returned by the chat graph carries a **deterministic, stable `.id`** that
  persists through the LangGraph checkpoint, so an enrichment job can correlate its result back to one
  message. Add `illustration_job_id` to the execute response (populated later in A3).
- **Read first:** `open_notebook/graphs/chat.py:137-185` (the `call_model_with_messages` node, AIMessage
  return at :178-180); `api/routers/chat.py:104-120,166-168,284-315` (`ChatMessage`, `ExecuteChatResponse`,
  `_build_chat_message` with the `msg_{fallback_index}` fallback at :307).
- **Spec / exact values:** Assign `id = f"ai-{uuid.uuid4().hex}"` only when the message lacks one.
  Set it in the existing `model_copy` update at `graphs/chat.py:178` so it round-trips in the checkpoint:
  `cleaned_message = ai_message.model_copy(update={"content": cleaned_content, "id": ai_message.id or f"ai-{uuid4().hex}"})`.
  Add `illustration_job_id: Optional[str] = None` to `ExecuteChatResponse` (`chat.py:166-168`).
- **Reuse:** existing `model_copy` pattern; `uuid` stdlib. `_build_chat_message` already reads `getattr(msg,"id",…)`
  at :307 — with a real id assigned, the `msg_{index}` fallback is no longer hit for AI messages (humans
  keep theirs; that's fine — only AI messages get illustrated).
- **Steps:**
  1. `import uuid` (or `from uuid import uuid4`) at the top of `graphs/chat.py`.
  2. Edit the `model_copy` at :178 to also set `id` (only if absent — never overwrite an existing id).
  3. Add `illustration_job_id: Optional[str] = None` to `ExecuteChatResponse`; return it as `None` for now
     in `execute_chat` (:648) — A3 will populate it.
- **Verify:** `uv run python -c "import open_notebook.graphs.chat"` imports clean. Send a chat message
  (UI or `curl POST /chat/execute`); confirm the AI message in the response has an `id` like `ai-…` (not
  `msg_0`), and that re-fetching the session (`GET /chat/sessions/{id}`) returns the **same** id (proves
  checkpoint persistence). `illustration_job_id` is present (null) in the execute response.

### Chunk A2 — Migration 18 + sidecar domain model + notebook field
- **Goal:** Create the greenfield persistence: a `chat_message_media` sidecar table keyed by message id,
  the `ChatMessageMedia` domain model, and the `notebook.auto_illustrate` boolean (default true). One
  migration (P-5).
- **Read first:** `open_notebook/database/migrations/17.surrealql` + `17_down.surrealql` (format);
  `migrations/1.surrealql:44-52` (notebook SCHEMAFULL table + `archived option<bool> DEFAULT False`);
  `open_notebook/database/async_migrate.py:96-183` (the explicit up/down lists, ending at 17);
  `open_notebook/domain/notebook.py:16-24` (`Notebook`) + a small `ObjectModel` subclass for the template;
  `open_notebook/domain/base.py:31-237` (base + `_prepare_save_data`, `nullable_fields`).
- **Spec / exact values:**
  - `migrations/18.surrealql`:
    ```surrealql
    -- Migration 18: auto-illustrate-chat.
    -- (a) Per-notebook toggle (default ON). notebook is SCHEMAFULL so the field must be declared.
    DEFINE FIELD IF NOT EXISTS auto_illustrate ON TABLE notebook TYPE option<bool> DEFAULT true;
    -- (b) Sidecar holding late-arriving chat illustration, keyed by the stable AI message id.
    DEFINE TABLE IF NOT EXISTS chat_message_media SCHEMAFULL;
    DEFINE FIELD IF NOT EXISTS message_id ON TABLE chat_message_media TYPE string;
    DEFINE FIELD IF NOT EXISTS session_id ON TABLE chat_message_media TYPE string;
    DEFINE FIELD IF NOT EXISTS mode ON TABLE chat_message_media TYPE string; -- 'image' | 'diagram' | 'none'
    DEFINE FIELD IF NOT EXISTS media ON TABLE chat_message_media FLEXIBLE TYPE option<object>;
    DEFINE FIELD IF NOT EXISTS diagram ON TABLE chat_message_media TYPE option<string>;
    DEFINE FIELD IF NOT EXISTS created ON chat_message_media DEFAULT time::now() VALUE $before OR time::now();
    DEFINE INDEX IF NOT EXISTS chat_message_media_message_id ON TABLE chat_message_media COLUMNS message_id UNIQUE;
    ```
  - `migrations/18_down.surrealql`:
    ```surrealql
    -- Rollback migration 18
    REMOVE INDEX IF EXISTS chat_message_media_message_id ON TABLE chat_message_media;
    REMOVE TABLE IF EXISTS chat_message_media;
    REMOVE FIELD IF EXISTS auto_illustrate ON TABLE notebook;
    ```
    (Confirm `REMOVE … IF EXISTS` syntax against an existing `*_down.surrealql`; match whatever the repo's
    down-migrations actually use — several just redefine fields. If `REMOVE` isn't used elsewhere, mirror
    the existing down-migration style instead.)
  - `Notebook.auto_illustrate: Optional[bool] = True` added to `open_notebook/domain/notebook.py:16-24`.
  - New `ChatMessageMedia(ObjectModel)` in `open_notebook/domain/notebook.py` (same file as other chat
    models — `ChatSession` lives here too): `table_name="chat_message_media"`, fields `message_id: str`,
    `session_id: str`, `mode: str`, `media: Optional[dict] = None`, `diagram: Optional[str] = None`;
    `nullable_fields = {"media", "diagram"}`. Add a classmethod `get_for_session(session_id) -> list` and
    `get_for_message(message_id) -> Optional[ChatMessageMedia]` via `repo_query`.
- **Reuse:** `ObjectModel.save()/get()`; `repo_query`, `repo_upsert` (`database/repository.py`);
  migration manager pattern (explicit list).
- **Steps:**
  1. Write `18.surrealql` and `18_down.surrealql`.
  2. Register both in `async_migrate.py` — append `AsyncMigration.from_file(".../18.surrealql")` after
     line 129, and `.../18_down.surrealql` after line 182.
  3. Add `auto_illustrate` to `Notebook`.
  4. Add the `ChatMessageMedia` model with the two query helpers.
- **Verify:** Restart API (`systemctl --user restart on-api`) and check `journalctl --user -u on-api` for
  "Migration successful. New version: 18". `uv run python -c "from open_notebook.domain.notebook import Notebook, ChatMessageMedia"`.
  In a quick `uv run python` snippet: create a `ChatMessageMedia(message_id='t1', session_id='s1', mode='none')`,
  `await .save()`, then `await ChatMessageMedia.get_for_message('t1')` returns it. Fetch a notebook and
  confirm `.auto_illustrate is True`.

### Chunk A3 — Hydrate-merge + submit enrichment job + notebook-update passthrough
- **Goal:** Close the loop: (1) `_build_chat_message` merges any sidecar row into the response message;
  (2) `execute_chat` submits the enrichment job (gated by the notebook toggle) and returns its
  `illustration_job_id`; (3) the notebook-update endpoint accepts `auto_illustrate` so the C3 toggle can
  persist it.
- **Read first:** `api/routers/chat.py:284-315` (`_build_chat_message`), `:569-648` (`execute_chat`,
  invoke at :630, `await session.save()` at :641); `api/podcast_service.py:95-96` (`submit_command` usage);
  `api/routers/notebooks.py` (the notebook update endpoint + its request schema — find where
  `chat_tag_colors`/`archived` are accepted and mirror).
- **Spec / exact values:**
  - **Hydrate-merge** (in `_build_chat_message`, or batched in the callers at `:644-646` and the
    `GET /chat/sessions/{id}` builder): for an AI message, look up `ChatMessageMedia.get_for_message(msg.id)`.
    To avoid N queries, prefer fetching all rows for the session once (`ChatMessageMedia.get_for_session`)
    and passing a `{message_id: row}` dict into `_build_chat_message`. Apply per P-3:
    - `mode == 'image'` and `media`: append `MediaItem(**row.media)` to the message's `media` list.
    - `mode == 'diagram'` and `diagram`: append `f"\n\n```mermaid\n{row.diagram}\n```"` to `content`
      (do this AFTER `_resolve_citations`, so citation parsing isn't disturbed).
    - `mode == 'none'`: nothing.
  - **Submit job** in `execute_chat` after `await session.save()` (:641), before building the response:
    find the last AI message in `result["messages"]`, read its `.id`; if `getattr(notebook, "auto_illustrate", True)`
    is truthy, `job_id = str(submit_command("open_notebook", "illustrate_message", {"session_id": full_session_id,
    "message_id": ai_id, "notebook_id": notebook.id, "model_id": model_override}))`; set
    `illustration_job_id = job_id` on the response. Wrap in try/except — a submit failure must NOT fail the
    chat turn (log + leave `illustration_job_id=None`). The `illustrate_message` command is built by Track B;
    submitting by name before the worker registers it is harmless (the job just won't be picked up yet).
  - **Notebook update:** add `auto_illustrate: Optional[bool] = None` to the notebook update request schema
    and pass it through to the notebook save (mirror how `chat_tag_colors`/`archived` flow through).
- **Reuse:** `submit_command` (import from the same place `podcast_service` does); `ChatMessageMedia`
  helpers from A2; existing `MediaItem`.
- **Steps:**
  1. Implement batched sidecar fetch + merge in the execute and get-session response builders.
  2. Add the toggle-gated `submit_command` call + populate `illustration_job_id`.
  3. Add `auto_illustrate` to the notebook update schema + passthrough.
- **Verify:** Manually insert a `chat_message_media` row (`mode='diagram', diagram='graph TD; A-->B'`) for a
  real AI message id, then `GET /chat/sessions/{id}` and confirm the message content gained a ` ```mermaid `
  block. Insert an `image` row and confirm the message `.media` gains the item. Send a chat message with the
  notebook toggle ON → response has a non-null `illustration_job_id` and a job row exists
  (`GET /commands/jobs/{id}` returns a status); toggle OFF (set `auto_illustrate=false` via the update
  endpoint) → `illustration_job_id` is null. `PUT`/update the notebook with `auto_illustrate:false` and
  confirm it persists. **At completion, announce Tracks B and C are unblocked.**

## Open Questions (this track)
- **Q-A-downsyntax** — exact `REMOVE`/redefine style for `18_down.surrealql`. *Default: match the
  prevailing style of existing `*_down.surrealql` files in the repo.*
- **Q-A-getsession** — confirm the `GET /chat/sessions/{id}` handler reuses `_build_chat_message` (so the
  merge lands in both read paths). *Default: route both through the same batched merge helper.*