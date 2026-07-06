# Chat Foundation — Backend chunk specs (B1–B6, N1–N2, N4)

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

---

# N-lane: Claude-agent efficiency + context meter *(added 2026-07-05)*

> Root cause context: a live chat with a book-sized context died with `[Errno 7] Argument list too
> long` — the Agent SDK passes the system prompt as ONE `--append-system-prompt` exec argument and
> Linux caps a single arg at 128 KiB. An **E2BIG hotfix** already landed directly in
> `open_notebook/ai/claude_agent.py` (system prompts >100KB reroute through stdin as a
> `<notebook_instructions>` transcript preamble; + 2 tests in `tests/test_claude_agent.py`).
> **N0 commits that hotfix first** — worktree subagents branch from committed history and would
> otherwise build against a claude_agent.py without it. All N-chunks build ON that change; never
> remove the oversize guard (it stays as the safety net under the slim index).

## N1 — AGENT-CTX: slim-index context for Claude-agent chats
- **Owns:** `open_notebook/graphs/chat.py`, `open_notebook/graphs/source_chat.py`. **Deps:** N0.
- **Goal:** When a chat routes to the Claude Agent SDK, stop pushing the full rendered context blob
  into the system prompt. Send a compact **source/note index** (ids + titles + abstract when already
  loaded) plus an explicit instruction to retrieve content on demand via the
  `mcp__open_notebook__*` tools (`search`, `get_source`, `get_source_outline`, `get_section`,
  `get_note`). The Esperanto/LangChain path is UNCHANGED (those providers may lack tools and need the
  pushed blob).
- **Why this is sound (decision N-1):** on the agent path the context selection was never an
  information boundary — the MCP tools are unscoped (`list_notebooks`/`search` reach everything), so
  replacing the blob with a whole-notebook index loses no access control, only redundant bytes.
- **Read first:** `graphs/chat.py:200-238` (`_generate_ai_message`; agent branch :212-221),
  `:241-258` (`call_model_with_messages` — renders `chat/system` :243, builds payload :248; holds
  `state`); `prompts/chat/system.jinja` (`{% if context %}` block — no template edit needed, `context`
  is just a string); `domain/notebook.py:90` (`get_sources(include_full_text=False)` — cheap listing);
  `ai/claude_agent_tools.py:67-207` (exact tool names); `graphs/source_chat.py` (analogous
  `generate_with_claude_agent` call :57 + its ContextBuilder). **Anchors have drifted before — re-verify
  line numbers against HEAD first (plan lesson).**
- **Spec:**
  - Thread what the index needs from `call_model_with_messages` into `_generate_ai_message` (it
    already receives `config`; add `state` or `notebook`). In the claude-agent branch, build
    `slim_context`:
    - header: "Notebook source index — full content is NOT inlined. Retrieve on demand with the
      mcp__open_notebook__ tools (search / get_source_outline / get_section / get_source / get_note)
      and cite ids exactly as listed."
    - one line per source: `- source:<id> — "<title>"` (+ ` — <abstract>` only when an abstract is
      already on the fetched record — do NOT add per-source insight round-trips beyond the one
      `get_sources()` + `get_notes()` pair);
    - one line per note: `- note:<id> — "<title>"`.
  - Re-render `Prompter(prompt_template="chat/system")` with a state copy where `context` =
    `slim_context`, and replace `payload[0]` (the SystemMessage) with the slim render — citation
    rules/quote block/notebook header stay intact.
  - **Degrade, never fail:** any error building the index → log a warning and keep the original
    payload (blob + E2BIG stdin guard still protect the turn).
  - Log one INFO line with before/after system-prompt byte sizes (observability; feeds the meter work).
  - `source_chat.py`: same pattern on its agent branch — replace the built source-context blob with
    `source:<id> — "<title>"` + a hint to use `get_source_outline`/`get_section` on that id.
- **Verify:** pure-function test for the index builder (sources/notes list → expected text). Live:
  claude-agent turn on the ML-book notebook → journalctl (`on-worker`) shows the size-drop log
  (≳100KB → <5KB), reply uses tools (`tool_uses` non-empty in `GET /chat/sessions/{id}`) and cites
  `[source:…]`. A turn on an Esperanto model (qwen3.6) routes with the blob unchanged (routing log
  says Esperanto; no slim log line). `uv run pytest tests/`.

## N2 — USAGE-BE: capture Agent-SDK token usage + context-window map
- **Owns:** `open_notebook/ai/claude_agent.py`, `open_notebook/ai/context_windows.py` (NEW),
  `api/routers/chat/schemas.py`, `api/routers/chat/citations.py`, `tests/test_claude_agent.py`.
  **Deps:** N0. Implements **frozen contract #9** (coordinator).
- **Goal:** Stop discarding the SDK's per-turn usage. `ResultMessage.usage` (dict: input/output/cache
  token counts — claude_agent_sdk `types.py:1032`) rides `AIMessage.additional_kwargs["usage"]` to the
  checkpoint, and surfaces on `ChatMessage.usage` at session read — the exact plumbing `tool_uses`
  already uses. A per-model context-window lookup supplies the denominator.
- **Read first:** `ai/claude_agent.py` — `_run` (ResultMessage handling; `AssistantMessage.model`
  carries the effective model) and `generate_with_claude_agent` (`additional_kwargs={"tool_uses": …}`
  precedent); `api/routers/chat/citations.py:118-123,151` (tool_uses read + attach);
  `api/routers/chat/schemas.py:60,96` (`ToolUseDisclosure`, `ChatMessage.tool_uses`).
- **Spec:**
  - `_run`: also capture `usage = message.usage or {}` from the `ResultMessage` and the last
    `AssistantMessage.model`; return them alongside `(text, tool_uses)`.
  - `generate_with_claude_agent`: build contract-#9 dict defensively (copy only int fields that
    exist: `input_tokens`, `output_tokens`, `cache_read_input_tokens`,
    `cache_creation_input_tokens`; add `model`) → `additional_kwargs["usage"]`; omit the key
    entirely when the SDK returned nothing.
  - `context_windows.py` (NEW): `get_context_window(model: str | None) -> int | None` — longest-prefix
    match over a small map: `claude-` → 200_000, aliases `opus`/`sonnet`/`haiku` → 200_000,
    `qwen3.6` → 262_144; `None` for unknown (meter hides). Values are Q-N-windowmap.
  - `schemas.py`: `class UsageInfo(BaseModel)` with the contract-#9 fields (all Optional) +
    `context_window: Optional[int]`; add `usage: Optional[UsageInfo] = None` to `ChatMessage`.
  - `citations.py` `_build_chat_message`: beside the tool_uses read, `raw = extra.get("usage")`; if a
    dict → `UsageInfo(**raw, context_window=get_context_window(raw.get("model")))`; malformed →
    `None` (log debug, never 500 a session read).
- **Verify:** extend `tests/test_claude_agent.py` — fake `query` yielding a ResultMessage with a usage
  dict → `additional_kwargs["usage"]` populated (model from AssistantMessage); no usage → key absent.
  `uv run pytest tests/test_claude_agent.py`. Live: claude-agent turn → last AI message in
  `GET /chat/sessions/{id}` has `usage.input_tokens > 0` and `usage.context_window == 200000`;
  an Esperanto-model message has `usage: null` and the session read is otherwise unchanged.

## N4 — RESUME: layered SDK session resume *(DEFERRED ⊘ — documented, not build-now)*
- **Owns (when built):** `open_notebook/ai/claude_agent.py`, `open_notebook/domain/notebook.py`,
  a NEW migration (next free number — check `migrations/` at build time), `commands/chat_commands.py`.
- **Design (decision N-3):** the LangGraph checkpoint stays the single source of truth; resume is a
  pure optimization layer. Store `sdk_session_id` + a history fingerprint (hash of message ids) on
  `chat_session`. Each turn: if a session id exists AND the current history is exactly
  last-fingerprint + append-only new turns → resume (send only the new user message); anything else
  (side-chat promote, hide/trash, context_config change, missing/expired CLI session file, model
  switch) → silently fall back to the stateless rebuild and store the fresh session id.
- **Why deferred:** after N1 the re-sent prefix is small, so resume's remaining win is tool-use
  memory across turns + latency — revisit with N2's usage numbers in hand. Do NOT build ahead of
  measurements.

## Open Questions (backend)
- **Q-A-downsyntax** — `18_down.surrealql` `REMOVE`/redefine style. *Default: match existing down files.*
- ~~**Q-A-getsession**~~ — RESOLVED 2026-07-02: there is only one message read path post-202
  (`GET /chat/sessions/{id}` → `_build_chat_message`); the hydrate lives inside it (B5 v2).
- **Q-N-windowmap** — exact context-window values (Claude 200K today; qwen3.6 262144 per Ollama
  metadata). *Default: the N2 map; unknown models return None and the meter hides.*
- **Q-N-abstract** — is an abstract cheaply available on the `get_sources()` listing without extra
  queries? *Default: include abstract only if already on the fetched record; titles-only otherwise.*
