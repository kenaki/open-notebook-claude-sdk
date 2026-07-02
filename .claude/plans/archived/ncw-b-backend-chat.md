# Plan B — Backend Chat Extensions (Notebook Multi-Chat Workspace)

> **One of 5 parallel plans.** Read `.claude/plans/notebook-chat-workspace.md` (the COORDINATOR) first
> for shared law: Decisions, Conventions, the pdf-plan Reconciliation (migration numbering!), and the
> cross-plan status table you must update when you finish.
> **Chunks:** 2 (sub-chat fields), 3 (structured citations), 4 (tool-use disclosure), 5 (media
> attachments). All backend.
> **Dependencies:** none — **start immediately**. Runs concurrently with **Plan A** (frontend); you
> share **zero files** with it.
> **Why these 4 are one plan:** they all edit `api/routers/chat.py` (`ChatMessage`),
> `open_notebook/graphs/chat.py`, `open_notebook/ai/claude_agent.py`, and `prompts/chat/system.jinja`.
> Keeping them in one chat avoids merge conflicts on those files. Do the chunks **in order** (2→3→4→5),
> one chunk per session is fine — they all live in this one plan/branch.

## Coordination (same working tree, sequential landing)
- **Files you own outright:** `open_notebook/domain/notebook.py`, the new migration pair +
  `async_migrate.py`, `api/routers/chat.py`, `open_notebook/graphs/chat.py`, `claude_agent.py`,
  `prompts/chat/system.jinja`, plus upload-helper reuse in `api/routers/sources.py`.
- **Migration number:** claim the next free number (16 if pdf-plan hasn't taken it; else 17). **Re-check
  `async_migrate.py` registration before claiming** — see coordinator Reconciliation.
- **`system.jinja`** is also touched by `pdf-viewer-citations.md`. Whoever lands second merges (keep
  both the followups block and the page-anchor instruction).
- **Plan D consumes your shapes** — keep the JSON shapes here exactly as specified (`Citation`,
  `ToolUseDisclosure`, `MediaItem`) so the frontend TS mirrors match. **Land B before D starts.**
- When done: update coordinator Cross-plan status row "B" → ☑ + Changelog.

## Resume prompt (fresh chat)
> Execute Plan B (Backend Chat Extensions) of the Notebook Multi-Chat Workspace. Read
> `.claude/plans/ncw-b-backend-chat.md` and the coordinator `.claude/plans/notebook-chat-workspace.md`
> in full. Do the next unstarted chunk in order (2→3→4→5), verify it, update this plan's Status table +
> the coordinator's Cross-plan status/Changelog, and tell me when it's safe to clear context.

## Status
| Chunk | Title | Status | Notes |
|------:|-------|--------|-------|
| 2 | Sub-chat fields (`parent_session_id`+`quote`) + migration + endpoints + prompt | ☑ done | Migration 16 applied once (DB@16); POST echoes + GET persists both fields (live-verified); SEED PASSAGE block renders only when `quote` set; `quote` threaded into `ThreadState`/`execute_chat`. test_domain 23 pass (8 pre-existing credential-test failures unrelated, confirmed on clean checkout). |
| 3 | Structured citations (schema + resolver + followups) | ☑ done | `Citation{id,type,number,title,snippet,page}` + `citations[]`/`followups[]` on `ChatMessage`; `_resolve_citations` helper (regex `(source_insight\|note\|source):id` tolerating `#p=<n>`, dedup+first-appearance numbering, async title/snippet fetch via `Source`/`Note`/`SourceInsight.get`, strips `---FOLLOWUPS---` block; markers KEPT inline); `_build_chat_message` used in both `execute_chat` + `get_session` (human→empty arrays). `system.jinja` FOLLOW-UP SUGGESTIONS block (conditional). Live-verified: real chat → citation w/ real title+snippet, 3 followups, sentinel stripped, marker kept, GET persists; test_domain 23 pass (same 8 pre-existing credential failures). |
| 4 | Tool-use disclosure capture (agent → `tool_uses[]`) | ☑ done | `_run` now returns `(text, tool_uses)`: collects `ToolUseBlock`s from `AssistantMessage` (keyed by id) + matches `ToolResultBlock`s off the synthetic `UserMessage` by `tool_use_id`; `_stringify_tool_result` flattens str/list[dict]/None. `generate_with_claude_agent` → `AIMessage(content, additional_kwargs={"tool_uses": [...]})` (survives `model_copy` + checkpoint). `ToolUseDisclosure{id,tool_name,tool_input,tool_result,is_error}` added to `chat.py`; `tool_uses: Optional[List[...]] = None` on `ChatMessage`, populated in `_build_chat_message` from `additional_kwargs.get("tool_uses")` (empty/absent → None). **Raw** MCP tool names kept (Q-toolnames default). Live-verified on "Greek learning": agent chat → `tool_uses[]` = 5 (incl. `mcp__open_notebook__search`×2 + `get_source` w/ inputs+results), GET persists exact shape; Ollama qwen Esperanto chat → `tool_uses=None`, HTTP 200, no crash. test_claude_agent 16 pass (5 new); test_domain 23 pass (same 8 pre-existing credential failures). |
| 5 | Media attachments (upload, schema, multimodal payload) | ☑ done | Shared upload helpers factored to `api/upload_utils.py` (`generate_unique_filename`/`save_uploaded_file(+folder)`/`resolve_within` guard); `sources.py` imports them (test patch target preserved). `CHAT_MEDIA_FOLDER=data/uploads/chat-media/` (config). `MediaItem{type,url,label,duration}` added; `media[]` on `ExecuteChatRequest` + `ChatMessage`; `POST /chat/media` (multipart, classifies image/video) + guarded `GET /chat/media/{file}`. `execute_chat` rides `media` on `HumanMessage.additional_kwargs` (checkpoint round-trip); `_build_chat_message` surfaces it (AI→empty). Esperanto path `_attach_media_blocks` inlines images as data-URIs (provision still sees text payload → token count unaffected), videos→text refs; agent path `_flatten` appends `[Attached media — …]` file refs (Decision 9 / Q-agentmedia). **Live-verified on "Greek learning":** upload→fetch (200, bytes match)+traversal-safe; agent-path execute w/ media → HTTP 200, AI saw "attachment reference for red.png", media[] round-trips on both human turns via GET (AI→[]). Esperanto path **built+sent** the image block to Ollama qwen3.6 → provider 400 "Failed to load image" = **model not vision-capable** (model-side image test BLOCKED on a vision model, payload-build verified). `_attach_media_blocks` unit-checked (data-URI image block + video text ref). test_domain/test_claude_agent/test_sources_api 53 pass. |

---

### Chunk 2 — Sub-chat fields + migration + endpoints + prompt injection
- **Goal:** A chat session can be created/read/updated with `parent_session_id` + `quote`, both
  persisted and returned; a session with a `quote` injects it into the chat system prompt. Testable
  via API alone.
- **Read first:** `open_notebook/domain/notebook.py` `ChatSession` (~679: `table_name`,
  `nullable_fields`, `model_override`, `relate_to_notebook/source`); `migrations/15.surrealql`(+down)
  for format; `database/async_migrate.py` (~98–123); `api/routers/chat.py`
  (`CreateSessionRequest`@22, `UpdateSessionRequest`@30, `ChatSessionResponse`@44, `create_session`@137,
  `get_session`@175, `update_session`@250, `get_sessions`@96, `execute_chat`@330, state assembly
  370–373); `open_notebook/graphs/chat.py` `ThreadState`@27; `prompts/chat/system.jinja`.
- **Exact values:** `parent_session_id: Optional[str] = None`, `quote: Optional[str] = None`. Migration
  **16** (confirm free vs pdf-plan first — see coordinator Reconciliation).
- **Reuse:** the `model_override` end-to-end pattern, copied through every layer.
- **Steps:** (1) add both fields to `ChatSession` + `nullable_fields`; (2) `migrations/16.surrealql`
  (documents the two schemaless fields) + `16_down.surrealql` (`REMOVE FIELD IF EXISTS …`), register
  both; (3) thread both fields through `Create/Update SessionRequest`, `ChatSessionResponse`, and all 5
  endpoint mappings (`getattr`); (4) add `quote: Optional[str]` to `ThreadState`; (5) in `execute_chat`
  set `state_values["quote"] = getattr(session, "quote", None)`; (6) in `system.jinja` add a
  `{% if quote %}# SEED PASSAGE … > {{ quote }}{% endif %}` block near the top.
- **Verify:** API boots, migration 16 logged once; `POST /chat/sessions` echoes both fields, `GET`
  persists them; `POST /chat/execute` on a quoted session replies normally (debug-log the rendered
  prompt to confirm the block). `uv run pytest tests/test_domain.py` green.

### Chunk 3 — Structured citations (schema + resolver + followups)
- **Goal:** `POST /chat/execute` and `GET /chat/sessions/{id}` return each AI message with
  `citations: list[Citation]` (resolved markers w/ titles/snippets) and `followups: list[str]`
  (parsed from a model block), with the followups block stripped from `content`.
- **Read first:** `api/routers/chat.py` (`ChatMessage`@37, conversions in `get_session` 199–210 and
  `execute_chat` 396–405); `frontend/src/lib/utils/source-references.tsx` (the regex
  `(source_insight|note|source):([a-zA-Z0-9_]+)`, dedup+number logic — **port numbering to backend**);
  `open_notebook/domain/notebook.py` `Source.get`/`Note.get`/`SourceInsight` (titles/snippets);
  `prompts/chat/system.jinja`.
- **Exact values:** `Citation{ id:str; type:Literal["source","note","source_insight"]; number:int;
  title:Optional[str]; snippet:Optional[str]; page:Optional[int]=None }` (`page` = pdf-plan hook).
  Followups sentinel: a literal `\n---FOLLOWUPS---\n`, one question per line.
- **Reuse:** the existing marker regex (tolerate optional `#p=<n>`); resolve in the **async** router
  functions (not the sync graph node).
- **Steps:** (1) add `Citation` + `citations`/`followups` to `ChatMessage`; (2) `_resolve_citations
  (content) -> (clean, citations, followups)` helper (regex-extract, dedup+number first-appearance,
  fetch title/snippet, split off the block); (3) call it in **both** `execute_chat` and `get_session`
  (human msgs → empty arrays; keep inline markers in `content` for back-compat); (4) `system.jinja`:
  instruct keep `[type:id]` markers + after the answer emit `---FOLLOWUPS---` then 2–3 short questions
  (conditional so short replies aren't forced).
- **Verify:** chat against a notebook with sources → AI message has populated `citations[]` (real
  titles/snippets) + `followups[]`; `content` has no `---FOLLOWUPS---`; `GET` persists the shape; no
  markers → empty arrays, no crash.

### Chunk 4 — Tool-use disclosure capture
- **Goal:** When chat routes through the Claude Agent, the AI message carries a `tool_uses[]` list
  (which MCP tools ran + inputs/results) so the UI can show "Searched your sources". No-op for the
  Esperanto path (empty list).
- **Read first:** `open_notebook/ai/claude_agent.py` (imports 17–23; `_run` 141–179 — the
  `async for message in query(...)` loop; `generate_with_claude_agent` 182–210);
  `open_notebook/ai/claude_agent_tools.py` (tool names: `list_notebooks`, `get_notebook`,
  `list_sources`, `get_source`, `get_note`, `search`); `open_notebook/graphs/chat.py`
  `_generate_ai_message`@35 + `call_model_with_messages`@55 (return @94); `api/routers/chat.py`
  `ChatMessage`@37 + conversion 396–405; SDK types in
  `.venv/.../claude_agent_sdk/types.py` (`ToolUseBlock`, `ToolResultBlock`).
- **Exact values:** `ToolUseDisclosure{ id:str; tool_name:str; tool_input:dict; tool_result:Optional
  [str]; is_error:Optional[bool] }`. Strip the `mcp__open_notebook__` prefix for display, or keep raw
  + map in the UI (Open Q-toolnames — default: send raw, map in UI).
- **Reuse:** `AIMessage` `additional_kwargs` to carry the list back through LangGraph; the existing
  `getattr(msg, ...)` conversion pattern in `execute_chat`.
- **Steps:** (1) import `ToolUseBlock`, `ToolResultBlock`; in `_run`, collect tool-use blocks (and
  match results by `tool_use_id`) into a list alongside `texts`; return `(text, tool_uses)` (adjust
  callers); (2) `generate_with_claude_agent` → `AIMessage(content=text, additional_kwargs={"tool_uses":
  tool_uses})`; (3) ensure `additional_kwargs` survives the graph (it rides on the message object);
  (4) add `tool_uses: Optional[list[ToolUseDisclosure]] = None` to `ChatMessage`; populate in
  `execute_chat`/`get_session` from `getattr(msg,"additional_kwargs",{}).get("tool_uses")`.
- **Verify:** chat via the Claude Agent on a notebook → response AI message `tool_uses[]` lists the MCP
  tools that ran with inputs; Esperanto-model chat → `tool_uses` empty/absent; no crash either path.
  **Run from source** (agent path needs the local Claude CLI).

### Chunk 5 — Media attachments (upload + schema + multimodal payload)
- **Goal:** An image/video can be uploaded and attached to a chat message; the message round-trips with
  `media[]`; on send, images are passed to the model as multimodal content (Esperanto path) and at
  minimum referenced on the agent path.
- **Read first:** `api/routers/sources.py` `save_uploaded_file` (73–94), `generate_unique_filename`
  (41–70), download (`_resolve_source_file` 588–610, `GET /sources/{id}/download` 702–716);
  `open_notebook/config.py:12` (`UPLOADS_FOLDER`); `api/routers/chat.py` `ExecuteChatRequest`@64 +
  `execute_chat` user-message build (369–379); `open_notebook/graphs/chat.py`
  `call_model_with_messages` (57–58 payload build, 90 text extract); `open_notebook/ai/provision.py`
  (LangChain `HumanMessage` supports `content: list[str|image_url]`); `claude_agent.py` `_flatten`
  (113–138, text-only).
- **Exact values:** `MediaItem{ type:Literal["image","video"]; url:str; label:str;
  duration:Optional[str] }` (mirror the handoff data model). Storage dir `./data/uploads/chat-media/`.
- **Reuse:** `save_uploaded_file` + `generate_unique_filename` + the download/serve + path-traversal
  guard pattern (factor a shared helper rather than copy).
- **Steps:** (1) `POST /chat/media` (multipart) → save under `chat-media/`, return `{url,label,type,
  duration?}`; add a guarded `GET /chat/media/{file}` (or reuse a static mount); (2) add
  `media: list[MediaItem] = []` to `ExecuteChatRequest` and to the AI/human `ChatMessage`; (3) in
  `execute_chat`, attach `media` to the `HumanMessage` (e.g. via `additional_kwargs`); (4) in
  `call_model_with_messages` build multimodal `HumanMessage.content` blocks (image_url/data-uri) for
  the Esperanto path when media present; on the agent path, append a textual reference (file
  name/path) — full agent multimodal = Open Q-agentmedia; (5) confirm LangGraph checkpoint serializes
  the extended message (test round-trip).
- **Verify:** `POST /chat/media` returns a fetchable url; `POST /chat/execute` with `media[]` on an
  Esperanto vision model → model receives the image (sanity: ask it to describe → relevant reply);
  message persists with `media[]` across `GET`; agent path doesn't crash with media present.

## Completion
When all four chunks are ☑: update the coordinator's Cross-plan status (row B → ☑) + Changelog,
announce "✅ Plan B complete — safe to clear context. Plan D's backend dependency is satisfied." stop.
