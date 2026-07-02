# Background Processes for Local-Model Work — Plan

## Context

Local models on the DGX Spark (ds4 / DeepSeek-V4-Flash, Ollama) take real time to
answer — ds4 has a cold start (lazy activator reloads the 81 GB model, up to ~180 s)
and a single-stream constraint. Today a notebook chat message is one **blocking** HTTP
call (`POST /chat/execute`, `read=600s`) and source chat is a **fake-SSE** blocking
call. Because the in-flight state lives in the notebook-scoped hook, leaving the page
makes the work feel lost/stuck.

**Goal:** turn slow local-model work into tracked **background jobs**. The user chats
normally but can leave the chat/page; a persistent bottom-corner **tray** lists
in-progress jobs with progress; when a response is ready a **notification** fires and
the originating chat shows the answer. The same tray surfaces *all* local-model work.

### User decisions (locked)
1. **Durability:** Server-side job queue — jobs run on the existing `surreal-commands`
   worker and survive browser refresh / tab close.
2. **Tray scope:** Unified — chat + podcasts + source processing/embeddings + transformations.
3. **Surfaces v1:** Notebook chat **and** source chat.

### Why this is the right shape
The hard half already works: notebook chat messages live in the **TanStack Query cache
keyed by `sessionId`** ([query-client.ts](frontend/src/lib/api/query-client.ts)), which
survives navigation. A finished answer can be re-injected into the right chat via
`queryClient.invalidateQueries` / `setQueryData` even after the user navigated away. And
the **job queue already exists** (`surreal-commands`, used by podcasts/embeddings/
sources) — a single worker process naturally **serializes** local-model jobs, which is
exactly what ds4's single-stream constraint needs. So this is mostly *relocating who
runs the chat graph* + *building the receive/tray/notification layer*, not new infra.

---

## Architecture decisions (load-bearing)

- **D1 — The worker becomes the sole writer of the LangGraph SQLite checkpoint.** All
  chat invokes move off the API into the `chat_completion` command. Since only one
  process (`on-worker`) ever writes `checkpoints.sqlite`, we avoid cross-process write
  contention; enable `PRAGMA journal_mode=WAL` + `busy_timeout=5000` on the shared
  connection in [chat.py](open_notebook/graphs/chat.py) and the source-chat graph so the
  API's existing checkpoint **reads** (`get_state` in `GET /chat/sessions/{id}`) stay
  safe. Per-session write serialization is guaranteed by the heavy-lane lock (D4) + one
  job per session. *Rejected:* a new SurrealDB message table — it duplicates the
  checkpoint and forces rewriting message extraction across the multi-panel chat.
- **D2 — Context is prebuilt and passed in job args.** The frontend already calls
  `buildContext()` → `POST /chat/context` before sending. Keep that; the job carries the
  resolved `context` dict (JSON-serializable). The worker re-fetches `Notebook` by id
  (id in args, not the object).
- **D3 — Media / model_override / Claude Agent ride in args.** `media` → `MediaItem`
  dicts; files read from the shared `CHAT_MEDIA_FOLDER` (same host). `model_override` is
  a string (incl. the `claude_agent` marker). Claude Agent spawns the Claude CLI
  subprocess — works unchanged from the worker (same filesystem). Reconstruct the
  `HumanMessage(additional_kwargs={"media": ...})` exactly as the endpoint does today.
- **D4 — Heavy-lane lock for ds4 single-stream.** The worker semaphore is **5 and shared
  across all command types**. Add a module-level `asyncio.Lock` in `commands/_heavy_lane.py`
  that `chat_completion` acquires around the model call **only when the resolved model is
  local/heavy** (ollama / ds4-openai_compatible / claude_agent). Local chats serialize
  against each other; embeddings keep running on the other semaphore slots; cloud chats
  stay parallel. Mirrors the existing ds4↔Ollama heavy-slot guardrails.
- **D5 — Status surface: implement the existing stub, no parallel endpoint.**
  [commands.py](api/routers/commands.py) already exposes `GET /commands/jobs`
  (`status_filter`, `command_filter`, `limit`) but `CommandService.list_command_jobs` is
  a stub returning `[]`. Implement it with a real `repo_query` over the `command` table
  and have the tray/poller call `GET /commands/jobs?status_filter=active`. Progress rides
  **inside `result`** (`{phase, partial_text}`) because surreal-commands' native
  `progress` field is always null; the command writes it via
  `command_service.update_command_result(input_data.execution_context.command_id, "running", {...})`
  mid-flight (same handle podcasts use to attach their episode record).
- **D6 — No DB migration required.** The `command` table is schemaless and already
  created by podcast jobs. *Optional* index `DEFINE INDEX command_status ON command
  FIELDS status` only if the active-jobs query is slow.

---

## Chunked implementation plan

Dependency order (│ = parallelizable once deps land):

```
1 backend: chat_completion command  ─┐
3 backend: list_command_jobs + active │  (1 ‖ 3 can start together)
2 backend: /chat/execute → 202 submit ┘  (2 needs 1)
4 frontend: global jobs store + poller    (needs 3)
5 frontend: notebook send/receive refactor (needs 2,3,4) ┐
6 back+front: source-chat → job            (needs 1,3,4)  ├ 5 ‖ 6 ‖ 7
7 frontend: unified tray UI                (needs 4)      ┘
8 frontend: notifications  (folds into 4/7)
9 i18n  (last — needs final key names from 5–8)
```

### Chunk 1 — Backend: `chat_completion` command *(foundation)*
- **Create** `commands/chat_commands.py`: `ChatCompletionInput(CommandInput)` =
  `{session_id, message, context: dict, model_override?, media: list[dict]=[],
  kind: 'notebook'|'source'='notebook', source_id?, notebook_id?, label=''}`;
  `ChatCompletionOutput(CommandOutput)` = `{success, session_id, error_message?}`
  (the full message list is read back from the checkpoint, not returned).
  `@command("chat_completion", app="open_notebook", retry={"max_attempts": 1})`
  (never silently re-run a model turn that may have partly persisted).
  - `kind=='notebook'`: replicate the body of `execute_chat`
    ([chat.py:600-638](api/routers/chat.py#L600)) inside the worker — load
    `ChatSession`, `Notebook.get(notebook_id)`, build `HumanMessage` + media kwargs,
    acquire heavy lane (D4), `chat_graph.invoke(...)`.
  - `kind=='source'`: same via `source_chat_graph` + `source_id`; write one
    `update_command_result(..., "running", {"phase":"generating","partial_text": text})`
    after the graph returns (pseudo-stream), then complete.
- **Create** `commands/_heavy_lane.py`: `heavy_lane = asyncio.Lock()` +
  `async def is_heavy_model(model_override) -> bool` (reuse `is_claude_agent_selected`
  + a provider check via `Model.get`/`ModelManager`).
- **Reuse unchanged:** `graphs/chat.py`, `graphs/source_chat.py`, `ai/claude_agent.py`.
  The existing async→sync ThreadPoolExecutor bridge in `call_model_with_messages`
  already supports being called from the worker's loop.
- **Edit** `graphs/chat.py` + source-chat graph: add WAL pragmas on the shared
  `sqlite3.connect(...)` (D1).

### Chunk 2 — Backend: `/chat/execute` → async submit *(needs 1)*
- **Edit** [chat.py](api/routers/chat.py) `execute_chat` (~569): keep session/notebook
  validation; replace `chat_graph.invoke` + reconcile with
  `CommandService.submit_command_job("open_notebook","chat_completion", args)`; return
  `202 {job_id, session_id}`. Guard-import `commands.chat_commands` (mirror
  [podcast_service.py](api/podcast_service.py)).
- **Edit** [chat.ts](frontend/src/lib/api/chat.ts) + `lib/types/api.ts`: `sendMessage`
  now returns `{ job_id, session_id }` (wiring in Chunk 5).

### Chunk 3 — Backend: active-jobs list *(parallel to 1/2)*
- **Edit** [command_service.py](api/command_service.py) `list_command_jobs` (stub):
  `repo_query("SELECT id,app,name,args,status,result,error_message,created,updated FROM
  command WHERE status IN ['new','running'] ORDER BY created DESC LIMIT $limit")` with
  optional `command_filter`/`status_filter` (treat `active` = `['new','running']`).
  Stringify RecordIDs. `args` is returned so the tray can derive
  `kind/sessionId/notebookId/source_id/label` for chat jobs, `episode_name` for podcasts.
- **Edit** [commands.py](api/routers/commands.py): no new route needed — the existing
  `GET /commands/jobs?status_filter=active` now works. (Optionally add a thin
  `GET /commands/active` alias.)
- **Create** `frontend/src/lib/api/commands.ts`: `commandsApi.listActive()`,
  `commandsApi.getJob(id)`.

### Chunk 4 — Frontend: global jobs store + app poller *(needs 3)*
- **Create** `frontend/src/lib/stores/jobs-store.ts` (Zustand + `persist`, template
  [auth-store.ts](frontend/src/lib/stores/auth-store.ts)). `BackgroundJob =
  {jobId, kind, sessionId?, targetId?, notebookId?, label, status, progress?,
  partialText?, startedAt, error?}`; actions `register/update/remove/clearFinished`;
  `partialize` to persist only the identity fields of in-flight jobs (status re-derived
  from server on reload). Store name `'jobs-storage'`.
- **Create** `frontend/src/lib/hooks/use-jobs-poller.ts`: `useQuery(['commands','active'],
  commandsApi.listActive, { refetchInterval: hasActive ? 4000 : false, meta:{silent:true} })`.
  Snappy initial cadence (~1.5 s ramping to 4 s) so quick cloud chats still feel live.
  Reconcile server jobs into the store; on chat job `completed` →
  `invalidateQueries(QUERY_KEYS.notebookChatSession(sessionId))` (or source key), clear the
  pending placeholder, fire toast (Chunk 8), `remove` after a grace; while `running` with
  `result.partial_text`, write it into the placeholder via `setQueryData`.
- **Create** `frontend/src/components/jobs/JobsRuntime.tsx` (renders nothing, calls the
  poller); **mount** in [(dashboard)/layout.tsx](frontend/src/app/(dashboard)/layout.tsx)
  so it runs only when authenticated.

### Chunk 5 — Frontend: notebook send/receive refactor *(needs 2,3,4)*
- **Edit** [useNotebookChat.ts](frontend/src/lib/hooks/useNotebookChat.ts) `sendMessageTo`
  (292-372): keep optimistic user message + auto-create-session; replace blocking call
  with `const {job_id} = await chatApi.sendMessage(...)` → `jobsStore.register({jobId,
  kind:'notebook_chat', sessionId, notebookId, label})` → insert an **assistant
  placeholder** (`id: 'pending-'+job_id, type:'ai', pending:true`). Receive is owned by
  the poller. Derive `getIsSending(sessionId)` from "store has an active job for this
  session" so multi-panel stays correct (every job keyed strictly by `sessionId` → no
  cross-panel bleed). Preserve the `{ ok:false }` draft-restore on submit failure.
- **Edit** message type + bubble renderer (ChatPanel + ChatDock + PoppedChatPanel) to
  show a skeleton for `pending` and an error state on failure.

### Chunk 6 — Source-chat → cache-backed + job-tracked *(needs 1,3,4; ‖ 5)*
- **Edit** [source_chat.py](api/routers/source_chat.py) send endpoint (~483): submit a
  `chat_completion` job with `kind='source'`; return `202 {job_id, session_id}` instead
  of the StreamingResponse (the "SSE" is already fake — one event after a blocking
  invoke — so no real streaming is lost). Keep `GET .../sessions/{sid}` (reads checkpoint).
- **Edit** [useSourceChat.ts](frontend/src/lib/hooks/useSourceChat.ts): move messages from
  component `useState` to the query cache keyed `QUERY_KEYS.sourceChatSession(sourceId,
  sessionId)`; mirror notebook chat (optimistic user msg, register `source_chat` job,
  pending placeholder); delete the manual SSE reader. Results now survive navigation and
  appear in the tray.

### Chunk 7 — Unified tray UI *(needs 4; ‖ 5/6)*
- **Create** `frontend/src/components/jobs/{JobTray,JobTrayItem,JobStatusBadge}.tsx`:
  fixed bottom-right panel reading `useJobsStore()` (already merged with server jobs by
  the poller). Collapsed pill = count + spinner; expanded = items with label, badge,
  phase. Extract the badge color map from
  [EpisodeCard.tsx](frontend/src/components/podcasts/EpisodeCard.tsx) into the shared
  `JobStatusBadge`. Click → navigate to origin (notebook+session / source / podcast).
  **Mount** `<JobTray/>` next to `<JobsRuntime/>` in the dashboard layout.

### Chunk 8 — Notifications *(folds into 4/7)*
- In the poller's completion/failure handlers fire Sonner toasts (via existing `toast`;
  `<Toaster/>` already mounted in [layout.tsx](frontend/src/app/layout.tsx)) with a
  "View" action that calls a shared `jobOrigin(job)` helper
  (`frontend/src/lib/utils/job-origin.ts`).

### Chunk 9 — i18n *(last)*
- Add a `jobs:` section to [en-US/index.ts](frontend/src/lib/locales/en-US/index.ts)
  (`jobs.tray.*`, `jobs.status.*`, `jobs.chatReady`, `jobs.chatFailed`, `jobs.view`,
  `jobs.generating`, …) and replicate the key set across all **14** locale dirs (English
  fallback values acceptable for non-en in v1; keys must exist).

---

## Risks & mitigations
1. **SqliteSaver written from the worker** (highest). → Single writer process (D1) + WAL
   + `busy_timeout`; API keeps reads only; heavy lane serializes same-session writes.
   *Verify:* two rapid same-session sends + a refresh, no `database is locked` in
   `journalctl --user -u on-worker`, both turns persisted in order.
2. **Decoupling send/receive in the recently-redesigned multi-panel chat.** → Every job
   keyed strictly by `sessionId`; placeholder + completion touch only that session's
   cache key; `getIsSending` derived per-session. *Verify:* concurrent sends in two
   popped panels land in the correct panels.
3. **Dropping "SSE" for source chat.** → It's already fake (single event post-invoke);
   approximate with one `result.partial_text` merge the poller renders. Acceptable.
4. **ds4 single-stream contention.** → Heavy-lane lock (D4), conditional on provider.
5. **Job-queue overhead on fast cloud chats.** → Snappy initial poll cadence (~1.5 s).

---

## Verification (end-to-end)
Services are systemd --user units; restart `on-api`/`on-worker` after backend edits,
`on-frontend` after frontend. Logs: `journalctl --user -u on-worker -f`.
1. **Submit + leave (notebook, ds4):** send → `202 {job_id}` + skeleton bubble; navigate
   away → tray shows running job with phase.
2. **Notify + regenerate:** worker finishes → success toast with "View" → clicking
   returns to the session with the answer rendered (placeholder replaced).
3. **Refresh mid-job:** send, hard-refresh while running → store rehydrates, first poll
   re-shows the job, answer appears on completion without re-sending.
4. **Source-chat parity:** repeat 1–3 from a source page; result survives navigation
   (previously lost) and shows in the tray; partial text flashes before completion.
5. **Unified tray:** kick off a podcast + a re-embed; both appear alongside chat jobs
   with correct badges; clicking navigates to origin.
6. **ds4 serialization:** two simultaneous sends to different sessions → worker log shows
   them run one-after-another while a parallel embedding still progresses.
7. **Failure path:** force a bad `model_override` → job `failed`, error toast, skeleton
   cleared, draft recoverable.

---

## Critical files
- **New:** `commands/chat_commands.py`, `commands/_heavy_lane.py`,
  `frontend/src/lib/stores/jobs-store.ts`, `frontend/src/lib/hooks/use-jobs-poller.ts`,
  `frontend/src/lib/api/commands.ts`,
  `frontend/src/components/jobs/{JobsRuntime,JobTray,JobTrayItem,JobStatusBadge}.tsx`,
  `frontend/src/lib/utils/job-origin.ts`.
- **Edit:** [api/routers/chat.py](api/routers/chat.py),
  [api/routers/source_chat.py](api/routers/source_chat.py),
  [api/command_service.py](api/command_service.py),
  [open_notebook/graphs/chat.py](open_notebook/graphs/chat.py) + source-chat graph,
  [frontend/src/lib/hooks/useNotebookChat.ts](frontend/src/lib/hooks/useNotebookChat.ts),
  [frontend/src/lib/hooks/useSourceChat.ts](frontend/src/lib/hooks/useSourceChat.ts),
  [frontend/src/app/(dashboard)/layout.tsx](frontend/src/app/(dashboard)/layout.tsx),
  `frontend/src/lib/api/chat.ts` + `source-chat.ts` + `lib/types/api.ts`,
  message-bubble components, and `frontend/src/lib/locales/*/index.ts` (14 dirs).

> Execution note: this is ~9 dependency-ordered chunks spanning disjoint backend/frontend
> files — a good fit for the `chunk-plan` → `chunk-plan-execute` worktree-orchestrator
> pipeline if you want waves 5‖6‖7 run in parallel.
