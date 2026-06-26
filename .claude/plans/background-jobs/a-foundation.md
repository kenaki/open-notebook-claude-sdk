# Background Jobs — Track A: Backend & Shared Foundation

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared decisions,
> conventions, concurrency, file ownership — then execute this track's chunks here, one per session.
> **Location:** `.claude/plans/background-jobs/a-foundation.md` → archived with the directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** none — this is the critical-path head.
**Concurrent with:** Track C (disjoint files). Track B starts once A4 + A5 are ☑.
**This chat owns ONLY:** `commands/*`, `open_notebook/graphs/{chat,source_chat}.py`,
`api/routers/chat/` (package: execute.py + schemas.py), `api/routers/source_chat.py`, `api/source_chat_service.py`, `api/command_service.py`, `api/routers/commands.py`,
`frontend/src/lib/api/{chat,commands}.ts`, `frontend/src/lib/types/api.ts`,
`frontend/src/lib/stores/jobs-store.ts`. Never touch Track B's `layout.tsx` or Track C's chat components.
**State at handoff (2026-06-25):** A1 implemented in the main session but **uncommitted**. First action:
verify + commit A1 as its own commit, then proceed to A2.
**Paste-able resume prompt — re-runnable (paste the SAME text on first run and every resume after `/clear`):**
> Continue Background-Jobs Track A. Read `.claude/plans/background-jobs/coordinator.md` (shared rules +
> Global status) then `.claude/plans/background-jobs/a-foundation.md` in full. Figure out where this track
> stands by reading its Status table AND cross-checking `git log` (one chunk = one commit), then pick the
> next unstarted chunk in order — don't assume a chunk number. Implement exactly that ONE chunk (reuse
> existing primitives; smallest faithful diff). Touch ONLY Track A's files. Verify with the chunk's verify
> steps; if red, fix or report — do not commit red. Commit just that chunk. Update BOTH this track file's
> Status table AND the coordinator's Global status table + Changelog. Announce "✅ Chunk A.n complete and
> verified — safe to clear context. Next: <derived>" and stop. If marking this ☑ makes EVERY track complete
> in the coordinator, archive the feature directory per the coordinator's Completion section.

## This track's file ownership
Creates/modifies: `commands/chat_commands.py`, `commands/_heavy_lane.py`, `commands/__init__.py`,
`open_notebook/graphs/chat.py`, `open_notebook/graphs/source_chat.py`, `api/routers/chat/execute.py`,
`api/routers/chat/schemas.py`, `api/routers/source_chat.py`, `api/source_chat_service.py`, `api/command_service.py`, `api/routers/commands.py`,
`frontend/src/lib/api/chat.ts`, `frontend/src/lib/api/commands.ts`, `frontend/src/lib/types/api.ts`,
`frontend/src/lib/stores/jobs-store.ts`.
Must NOT touch: `frontend/src/app/(dashboard)/layout.tsx` (Track B), `ChatPanel.tsx` / chat hooks (Track C).

## Per-chunk workflow
read referenced files → implement → verify → commit → mark ☑ here AND in coordinator → note new Open
Questions → announce "✅ Chunk A.n complete — safe to clear context" → stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| 1 | chat_completion command + heavy-lane + WAL + register | ☑ done | main session | verified committed (bundled in 827bf48) |
| 2 | `/chat/execute` → 202 submit (+ chat.ts/api types) | ☑ done | main session | commit bbce67b; tsc+pytest green |
| 3 | source_chat send → 202 submit | ☐ todo | | |
| 4 | status API: active `list_command_jobs` + `commands.ts` | ☐ todo | | unblocks Track B |
| 5 | shared `jobs-store.ts` (Zustand + persist) | ☐ todo | | unblocks B & C2/C3 |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- 2026-06-25 — A1 implemented in main session (uncommitted): `chat_commands.py`, `_heavy_lane.py`, WAL
  pragmas on both chat graphs, `__init__.py` registration.
- 2026-06-26 — A2 ☑: `execute_chat` → 202 submit via CommandService; `ExecuteChatJobResponse` added
  to schemas.py + types/api.ts; `chatApi.sendMessage` return type updated; command_service guard-import
  upgraded to full `commands` package. compat `messages` shim on response type keeps tsc green (Track C / C2 cleans up).

## Chunks (verbatim)

### Chunk 1 — chat_completion command + heavy-lane + WAL + register  ☑ DONE (commit pending)
- **Goal:** run notebook+source chat in the worker as a `chat_completion` surreal-command; serialize heavy
  local models; make the worker the sole checkpoint writer.
- **What's already on disk (verify, don't rewrite):**
  - `commands/chat_commands.py` — `ChatCompletionInput/Output` + `@command("chat_completion", app="open_notebook", retry={"max_attempts":1})`. Runs `chat_graph`/`source_chat_graph` via `asyncio.to_thread`, acquires `heavy_lane` when `is_heavy_model`, re-raises classified errors so the job marks `failed`.
  - `commands/_heavy_lane.py` — `heavy_lane = asyncio.Lock()` + `is_heavy_model(model_override)` (claude_agent or provider ∈ {ollama, openai_compatible}).
  - `open_notebook/graphs/chat.py` + `graphs/source_chat.py` — `PRAGMA journal_mode=WAL` + `busy_timeout=5000` on the shared `sqlite3.connect`.
  - `commands/__init__.py` — imports/exports `chat_completion_command`.
- **Verify:** `uv run python -c "import commands; print('chat_completion' )"` registers cleanly (no import
  error); `uv run python -c "import open_notebook.graphs.chat, open_notebook.graphs.source_chat"`.
  Restart `on-worker`, confirm `journalctl --user -u on-worker -n 50` shows the command registered, no
  traceback. **Then commit as A1.**

### Chunk 2 — `/chat/execute` → 202 submit
- **Goal:** the notebook chat endpoint submits a `chat_completion` job and returns `{job_id, session_id}`
  instead of blocking on `chat_graph.invoke`.
- **Read first:** `api/routers/chat/execute.py` (`execute_chat` ~26–84); `api/routers/chat/schemas.py` (`ExecuteChatRequest` ~125, `ExecuteChatResponse` ~139); `api/command_service.py` (`submit_command_job`); `commands/chat_commands.py` (input shape).
- **Steps:**
  1. In `execute_chat`: keep the session lookup + `refers_to` notebook resolution + model_override
     precedence (request > session). Then resolve `notebook_id = str(notebook.id) if notebook else None`.
  2. Replace the `chat_graph.get_state` + `HumanMessage` build + `chat_graph.invoke` + message-reconcile
     block with: `job_id = await CommandService.submit_command_job("open_notebook", "chat_completion", {session_id, message, context, model_override, media:[m.model_dump() for m in request.media] if request.media else [], kind:"notebook", notebook_id, label: request.message[:60]})`.
  3. Return `202` with a new `ExecuteChatJobResponse(BaseModel){ job_id:str, session_id:str }` (add the
     model near the other chat models; set `status_code=202` on the route or return a `JSONResponse`).
  4. Leave `GET /chat/sessions/{id}` untouched — it reads the checkpoint the worker writes.
- **Frontend contract:** in `frontend/src/lib/api/chat.ts`, change `sendMessage` to return
  `{ job_id: string; session_id: string }`; update the type in `frontend/src/lib/types/api.ts`. Do NOT
  touch `useNotebookChat.ts` (Track C owns the consumer).
- **Reuse:** `submit_command_job` already guard-imports `commands` (so `chat_completion` is registered).
- **Verify:** restart `on-api`; `POST /chat/execute` (Swagger at :5055/docs or curl with a real session)
  returns `202 {job_id}`; `journalctl --user -u on-worker -f` shows the job run + complete; the assistant
  message appears via `GET /chat/sessions/{id}`. `cd frontend && npx tsc --noEmit` passes.

### Chunk 3 — source_chat send → 202 submit
- **Goal:** the source-chat endpoint submits a `chat_completion` job (`kind:"source"`) and returns
  `{job_id, session_id}` instead of an SSE `StreamingResponse`.
- **Read first:** `api/routers/source_chat.py` (`send_message_to_source_chat` ~341; imports `stream_source_chat_response` from service at line 10); `api/source_chat_service.py` (`stream_source_chat_response` ~18); `commands/chat_commands.py` (source branch).
- **Steps:**
  1. Keep source/session validation + `refers_to` relation check + model_override resolution.
  2. Replace the `StreamingResponse(stream_source_chat_response(...))` with
     `job_id = await CommandService.submit_command_job("open_notebook", "chat_completion", {session_id, message, model_override, kind:"source", source_id: full_source_id, label: request.message[:60]})` and return `202 {job_id, session_id}`.
  3. Remove/retire `stream_source_chat_response` (dead once unused; the "SSE" was already a single post-invoke event, so no real streaming is lost). Keep `GET .../sessions/{sid}` (reads checkpoint).
- **Verify:** restart `on-api`; POST a source-chat message → `202 {job_id}`; worker log shows the source
  job; `GET .../sessions/{sid}` returns the new assistant turn.

### Chunk 4 — status API: active `list_command_jobs` + `commands.ts` client
- **Goal:** implement the stubbed jobs list so the tray/poller can fetch all active jobs; add the frontend
  API client.
- **Read first:** `api/command_service.py` (`list_command_jobs` stub ~70–80, `get_command_status`),
  `api/routers/commands.py` (`GET /commands/jobs` ~88–105), `open_notebook/database/repository.py` (`repo_query`, RecordID stringify helper), `commands/podcast_commands.py` (args shape for the tray).
- **Steps:**
  1. Implement `list_command_jobs(command_filter, status_filter, limit)` with
     `repo_query("SELECT id, app, name, args, status, result, error_message, created, updated FROM command WHERE …")`. Treat `status_filter == "active"` as `status IN ['new','running']`; pass `command_filter` as a `name = $name` clause; `ORDER BY created DESC LIMIT $limit`. Stringify `id` (and any RecordIDs in `args`) so the response is JSON-safe.
  2. Confirm `GET /commands/jobs?status_filter=active` returns the rows (route already exists). Optionally
     add a thin `GET /commands/active` alias delegating to the same.
  3. Create `frontend/src/lib/api/commands.ts`: `commandsApi.listActive()` → `GET /commands/jobs?status_filter=active&limit=100`; `commandsApi.getJob(id)` → `GET /commands/jobs/{id}`. Type the row (`CommandJobSummary { job_id; name; status; result; error_message; created; updated; args }`) in `lib/types/api.ts`.
- **Reuse:** `repo_query` + the repository's RecordID parsing; the existing `CommandJobStatusResponse`.
- **Verify:** restart `on-api`; kick off a podcast or source re-embed and confirm it appears in
  `GET /commands/jobs?status_filter=active`; `npx tsc --noEmit` passes. **Marking A4 ☑ unblocks Track B.**

### Chunk 5 — shared `jobs-store.ts` (Zustand + persist)
- **Goal:** the single global jobs store both Track B (poller/tray) and Track C (send path) import.
- **Read first:** `frontend/src/lib/stores/auth-store.ts` (persist pattern), coordinator Decisions.
- **Spec (exact shape):**
  ```ts
  type JobKind = 'notebook_chat' | 'source_chat' | 'podcast' | 'source' | 'transformation'
  type JobStatus = 'new' | 'running' | 'completed' | 'failed'
  interface BackgroundJob {
    jobId: string; kind: JobKind; sessionId?: string; targetId?: string;
    notebookId?: string; label: string; status: JobStatus;
    progress?: { phase?: string }; startedAt: string; error?: string
  }
  ```
  Actions: `register(job)`, `update(jobId, patch)`, `remove(jobId)`, `clearFinished()`, plus a selector
  `hasActiveForSession(sessionId)` (used by Track C's `getIsSending`).
- **Steps:** create the store with Zustand `persist`, name `'jobs-storage'`, `partialize` to persist only
  identity fields of in-flight jobs (`jobId, kind, sessionId, targetId, notebookId, label, startedAt`) so
  status is re-derived from the server poll on reload. Export `useJobsStore`.
- **Verify:** `npx tsc --noEmit` passes; import the store in a scratch component renders without error.
  **Marking A5 ☑ unblocks Track B fully and Track C's C2/C3.**

## Open Questions (this track)
- **Q-commit-A1** — A1 is implemented but uncommitted; the first session must verify + commit it before A2
  so `git log` reflects one-chunk-one-commit. (Default: commit as `feat(jobs): chat_completion worker command + heavy lane`.)