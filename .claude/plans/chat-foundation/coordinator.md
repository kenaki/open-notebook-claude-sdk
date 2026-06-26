# Chat Foundation — Coordinator (orchestrator-owned master doc)

> **Merged plan.** This combines two features that collide on the same files:
> **per-chat-context** (each side chat gets its own optional context selection) and
> **auto-illustrate-chat** (AI teaching messages auto-acquire a Mermaid diagram or a searched image
> via an async progressive-enhancement job). They are **orthogonal in the data model** — three
> independent schema additions, no relationship between them — so the merge is purely about
> eliminating file contention and maximizing safe parallelism.
>
> **Execution mode: worktree orchestrator.** This doc is built for `/chunk-plan-execute`. The executor
> parses the **Global status table** (chunk ids + deps + owned files), runs each wave of dependency-free
> chunks in parallel via **isolated git-worktree subagents**, integrates them, runs the cross-cutting
> verify, and is the **single writer** of the status table + changelog. Do **not** hand-run these in
> parallel chats against one working tree — several lanes edit the same file in different regions and
> rely on worktree isolation + integration merge.
>
> **Location:** `.claude/plans/chat-foundation/` → archived to `.claude/plans/archived/chat-foundation/`
> when every chunk is ☑.
> **Reference inputs (deep context, read-only):** `.claude/plans/auto-illustrate-chat/brief.md` +
> `.claude/plans/auto-illustrate-chat/tech-scout.md` (auto-illustrate goal/why + chosen stack); the
> per-chat-context rationale is folded into this doc. Both source plan dirs are **SUPERSEDED** by this one.

## How the orchestrator runs this (read first)
1. Parse the **Global status table**: each row is one chunk with its **Depends-on** and **Owns (files)**.
2. A chunk is **runnable** when every dep is ☑. Run all runnable chunks in a wave **in parallel**, each
   in its own worktree subagent, handing it the matching chunk spec from the area file named in its row.
3. Worktrees isolate **files**, not the **shared database/services**. The systemd `on-api`/`on-worker`
   units and the SurrealDB instance are shared. So any chunk whose *verify* hits the DB cannot truly
   verify until **MIG (B1)** has been integrated and the migration applied. Honor the deps — they encode
   this. After integrating a wave that changed backend code, `systemctl --user restart on-api`
   (and `on-worker` if a command changed) before running DB-dependent verifies.
4. Integrate each wave, run the per-chunk verify, then update the Global status table + Changelog here.
5. **Human gates:** pause at **the S-gate** (B7 spike → GO / GO-WITH-ADJUSTMENTS / NO-GO; W2/W3 are
   conditional on it) and at any Open Question marked needs-user. Do not guess these.
6. **Services run as systemd --user units** (`on-api`, `on-worker`, `on-frontend`) — never launch them;
   restart to apply. Logs via `journalctl --user -u on-api` etc.

## Frozen contracts (the parallelization enabler — every lane codes against these)
All field names / shapes / job args are **fixed here**, so downstream lanes write code against the spec
without waiting on upstream lanes. Only *runtime verification* honors the dependency order.

1. **Migration 18** (single migration, all three schema changes — see B1 spec).
2. **`chat_session.context_config`** — `FLEXIBLE TYPE option<object> DEFAULT NONE`. `null`/absent =
   **inherit** the global drawer selection; an object = this chat's **own** selection. Shape (stored
   opaquely by the backend; only the frontend interprets it):
   ```jsonc
   // null → inherit; object → explicit per-chat selection (modes: "off" | "insights" | "full")
   { "sources": { "<source:id>": "insights" }, "notes": { "<note:id>": "full" } }
   ```
   This is the frontend `ContextSelections` shape (`@/lib/types/notebook-context`).
3. **`notebook.auto_illustrate`** — `option<bool> DEFAULT true`. Per-notebook toggle, default ON.
4. **`chat_message_media` sidecar** — `{ message_id, session_id, mode: 'image'|'diagram'|'none',
   media: object|null, diagram: string|null, created }`, one row per illustrated AI message, UNIQUE
   index on `message_id`. Hydrate merge (per P-3): `mode='image'` → append `MediaItem(**media)` to the
   message's `.media`; `mode='diagram'` → append a fenced ` ```mermaid\n{diagram}\n``` ` block to
   `.content` (AFTER citation resolution); `mode='none'` → nothing.
5. **Stable AI message id** — every AI message returned by `/chat/execute` and `/chat/sessions/{id}`
   carries a real `.id` (`ai-{uuid4().hex}`, assigned at `graphs/chat.py:178`, persists in the
   checkpoint). The enrichment job is submitted with `(session_id, message_id, notebook_id, model_id)`.
6. **`ExecuteChatResponse.illustration_job_id: Optional[str]`** — populated by the background-jobs
   `chat-completion` worker command (Track C2), **not** inline in `execute_chat` (see compat note in B5).
   Set when a job was submitted (toggle ON + an AI message produced); else `None`. **Frontend does NOT
   build its own poll loop** — register this id in `useJobsStore` (kind: `'illustration'`);
   `use-jobs-poller.ts` (background-jobs Track B1) invalidates the session on completion (see F3).
7. **Job output (`CommandOutput`)** — `{ success, mode, message_id, error_message?, processing_time }`.
   Frontend only needs terminal status; on success it **invalidates the session query** (P-4) and the
   merged illustration hydrates from the backend (single source of truth).
8. **i18n key namespaces (collision-free locale edits):** FE-POPOVER owns `chat.context*`
   (`contextForThisChat`, `resetToNotebookDefault`, `inheritingNotebookDefault`, `contextIncludedCount`);
   FE-TOGGLE owns `chat.autoIllustrate*` (`autoIllustrate`, `autoIllustrateHelper`). Disjoint keys →
   clean worktree merge across `frontend/src/lib/locales/*`.

## Global status table (orchestrator owns this)
Chunk ids are stable. **Owns (files)** is the conflict key; **Depends-on** drives wave computation.

| Chunk | Lane | Area file | Title | Owns (files) | Depends-on | Status |
|------:|------|-----------|-------|--------------|------------|--------|
| P1 | PRE | — | Background-jobs plan prerequisite (chat-foundation runs after background-jobs lands) | cross-plan gate only | — | ☐ |
| P2 | PRE | — | Re-anchor plan docs + async compat fixes (post-refactor paths + B5/F3 compat bakes) | `coordinator.md`, `backend.md`, `frontend.md`, `worker.md` | — | ☑ |
| B1 | MIG | backend.md | Migration 18 (all 3 schema changes) + register | `migrations/18.surrealql`, `18_down.surrealql`, `database/async_migrate.py` | — | ☐ |
| B2 | MODELS | backend.md | Domain models: `ChatMessageMedia` + `Notebook.auto_illustrate` + `ChatSession.context_config` | `open_notebook/domain/notebook.py` | B1 | ☐ |
| B3 | MSGID | backend.md | Stable AIMessage `.id` + `illustration_job_id` field on response | `open_notebook/graphs/chat.py` | — | ☐ |
| B4 | CTX-CRUD | backend.md | `context_config` on session schemas + create/update/get | `api/routers/chat/schemas.py` + `api/routers/chat/sessions.py` | B2 | ☐ |
| B5 | HYDRATE-JOB | backend.md | Hydrate-merge sidecar + `illustration_job_id` field (trigger in worker — see compat note) | `api/routers/chat/citations.py`, `api/routers/chat/execute.py`, `api/routers/chat/schemas.py` | B2, B3 | ☐ |
| B6 | NB-API | backend.md | `auto_illustrate` passthrough on notebook-update | `api/routers/notebooks.py`, `api/models.py` | B2 | ☐ |
| B7 | SPIKES | worker.md | R3 vision + R4 relevance spikes → **S-gate** | scratch scripts only | — | ☐ |
| W1 | WORKER | worker.md | Enrichment command skeleton: gate → route → **diagram** → sidecar | `commands/illustrate_commands.py`, `open_notebook/graphs/illustrate.py`, `prompts/illustrate/` | B2, B5 | ☐ |
| W2 | WORKER | worker.md | **Image** pipeline: expand → search → VLM relevance/abstain | (same as W1) | W1, **B7 (S-gate GO)** | ☐ |
| W3 | WORKER | worker.md | **Image** safety (fail-closed) + SSRF fetch → WebP → store → sidecar | (same as W1) | W2 | ☐ |
| F1 | FE-TYPES | frontend.md | Types + chat-api passthrough (`context_config`, `illustration_job_id`, `auto_illustrate`) | `frontend/src/lib/types/api.ts`, `frontend/src/lib/api/chat.ts` | — | ☐ |
| F2 | FE-HOOK | frontend.md | `useNotebookChat`: per-session context resolution + quote-only seed + setter | `frontend/src/lib/hooks/useNotebookChat.ts` | F1 | ☐ |
| F3 | FE-HOOK | frontend.md | `useNotebookChat`: illustration job-poll → invalidate on complete (via `use-jobs-poller`) | `frontend/src/lib/hooks/useNotebookChat.ts` | F1, F2 | ☐ |
| F4 | FE-MERMAID | frontend.md | Mermaid renderer (strict + DOMPurify + parse-or-fallback) | `components/source/chat/Mermaid.tsx` (new), `components/source/chat/MarkdownCodeBlock.tsx`, `components/source/chat/ChatPanel.tsx` | — | ☐ |
| F5 | FE-POPOVER | frontend.md | Side-chat Context popover + i18n (`chat.context*`) | `components/notebooks/chat/PoppedChatPanel.tsx`, `components/notebooks/chat/SideChatContextPopover.tsx` (new), `components/notebooks/workspace/DeepDiveWorkspace.tsx`, `locales/*` | F1, F2 | ☐ |
| F6 | FE-TOGGLE | frontend.md | Per-notebook auto-illustrate toggle + i18n (`chat.autoIllustrate*`) | `components/notebooks/chat/SideChatDefaultMenu.tsx`, `components/notebooks/chat/ChatDock.tsx`, `components/notebooks/workspace/NotebookWorkspaceProvider.tsx`, `locales/*` | F1 | ☐ |

Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

> **Same-file note (worktree-required):** B4 and B5 now edit **different files** in the
> `api/routers/chat/` package (B4: `schemas.py` + `sessions.py`; B5: `citations.py` + `execute.py` +
> `schemas.py`), so there is no per-function file conflict — but worktree isolation still applies for clean
> integration. F2 and F3 both edit the **same function** (`sendMessageTo`) in `useNotebookChat.ts`, so
> F3 is sequenced **after** F2 even with worktrees.

## Computed waves (what the orchestrator will schedule)
- **Wave 1 (5 parallel):** B1, B3, B7, F1, F4 — all dep-free; each self-verifies (B1 applies the migration).
- **Wave 2 (3 parallel):** B2 (B1✓), F2 (F1✓), F6 (F1✓).
- **Wave 3 (5 parallel):** B4 (B2✓), B5 (B2,B3✓), B6 (B2✓), F3 (F2✓), F5 (F2✓).
- **Wave 4:** W1 (B5,B2✓).  **Wave 5:** W2 (W1✓ + S-gate GO).  **Wave 6:** W3 (W2✓).
- **Peak concurrency = 5** (waves 1 & 3). **Critical path = the worker tail** W1→W2→W3 (gated on B7);
  no agent count shortens it. Frontend (F1→F2→F3/F5) and the rest of backend finish well before W3.

## Decisions log (shared)
Carried verbatim from the two source plans; merge-specific decisions are **C-***.
| # | Question | Decision |
|--:|----------|----------|
| C-1 | How to combine two file-colliding plans | **One migration (18), file-disjoint lanes, worktree orchestration.** One owner per file (or per-function with worktree isolation for `chat.py`). Eliminates the verified migration-18 / `chat.py` / `notebook.py` / `sendMessageTo` collisions. |
| C-2 | One migration vs two | **Single migration 18** carries all three schema changes (user-chosen). Changes are independent; one version bump, atomic landing. |
| C-3 | i18n collision (popover + toggle both edit locales) | **Namespaced keys** (`chat.context*` vs `chat.autoIllustrate*`) → disjoint additions auto-merge across worktrees; no serial locale lane. |
| G-persist | Where late media lives | New `chat_message_media` **sidecar**, merged at hydrate — not a checkpoint patch. |
| G-msgid | Message→job correlation | Deterministic stable AIMessage `.id` at `graphs/chat.py:178`. |
| G-scope-modes | v1 illustration scope | **Both** diagram + image, routed per message. |
| G-control | Illustration noise control | **Per-notebook toggle, default ON.** |
| G-transport | Which chat illustrates | **Notebook chat only** (sync `POST /chat/execute`); source-chat SSE deferred. |
| ctx-1 | Where per-chat context lives | Persisted nullable `context_config` on `chat_session`. Survives reload. |
| ctx-2 | `null` vs object semantics | `null`/absent → inherit global drawer; object → own selection. |
| ctx-3 | Default for a new side chat | **Quote only** — seed explicit empty `{ sources:{}, notes:{} }`; relies on the `quote` seed passage. (Drops the `insightsSnapshot` helper — do NOT add it.) |
| ctx-4 | Dock/main chat behavior | Unchanged — never sets `context_config`, keeps the global drawer selection. |
| ctx-5 | "Reset to notebook default" | Sets `context_config = null` → inherit again. |
| D1 | Diagram render | Mermaid via react-markdown code-block; `securityLevel:'strict'` + DOMPurify on SVG + `mermaid.parse()` guard + **fallback-to-codeblock**. |
| D2 | Image relevance | qwen3.6 query-expansion + qwen3.6 VLM yes/no + **abstain** (rank+threshold). |
| D3 | Image safety | qwen3.6-VL zero-shot judge, **fail-closed**. |
| D4 | Image sources v1 | Wikipedia/Wikimedia Commons (incl. PageImages) + Openverse. |
| D5 | Delivery | surreal-commands job + frontend polling + persistence. |
| D6 | AI models | **Reuse qwen3.6 for ALL AI steps** (gate, expansion, relevance, safety); no new models. |
| P-1 | Spike sequencing | **Gate the image build (W2/W3) on the S-gate** (B7). Diagram (W1) + shared infra proceed regardless. |
| P-2 | Toggle UI location | Chat dock-header dropdown, mirroring `SideChatDefaultMenu`. |
| P-3 | Diagram carrier | Sidecar stores mermaid source; hydrate appends a ` ```mermaid ` fence (no new `ChatMessage` field). Image stores a `MediaItem` merged into `.media`. |
| P-4 | FE illustration delivery | On job completion, **invalidate the session query** (don't hand-patch client-side). |

## Conventions / translation notes (shared)
- **Migration:** `18.surrealql` + `18_down.surrealql`; register BOTH in `async_migrate.py` (up list ends
  at 17 near line 127-129; down list mirrors near line 182). Runs automatically on API startup. `notebook`
  and `chat_session` are **SCHEMAFULL** — undeclared fields are dropped on save, so every field MUST be in
  the migration.
- **Domain models:** subclass `ObjectModel` (`open_notebook/domain/base.py:31-237`); set `table_name`; use
  `repo_query/repo_create/repo_upsert`; `nullable_fields` ClassVar for null-able fields.
- **AI calls in the worker:** reuse `provision_langchain_model(text, model_id, "chat", max_tokens=…)`
  (`graphs/chat.py:131`); for image judging reuse `_attach_media_blocks()` / `_media_to_data_uri()`
  (`graphs/chat.py:70-105`) to build `image_url` data-URI blocks.
- **Error handling:** wrap LLM calls with `classify_error()` (see `graphs/CLAUDE.md`). The enrichment job
  must NEVER raise into the chat turn — separate worker process; on any failure write a `mode='none'` row
  (or nothing) and the message stays text-only.
- **Silent FE updates:** per-session writes use the silent pattern (direct `chatApi.updateSession` +
  targeted invalidation, no toast) — mirror `setSessionModelOverride` (`useNotebookChat.ts:523-536`).
- **i18n:** every new UI string needs a key in **all** locales under `frontend/src/lib/locales/*`
  (en-US is the reference). Use the namespaces in Frozen-contract #8.
- **Model id:** enrichment uses the already-registered local **qwen3.6**; confirm its exact record id from
  `scripts/register_ollama_models.py`/`DefaultModels` at build (a lookup, not a fork). `OLLAMA_API_BASE`
  must be set (verified in B7).

## Reference index (shared, confirmed against the codebase)
- `_attach_media_blocks` / `_media_to_data_uri` — `graphs/chat.py:40-105` (`_media_to_data_uri` :40, `_attach_media_blocks` :70)
- AIMessage return via `ai_message.model_copy(update={...})` — `graphs/chat.py:178` (B3 adds `"id"`)
- `provision_langchain_model(...)` — `graphs/chat.py:129`; graph handle (`graph = agent_state.compile(...)`) — `graphs/chat.py:199-203`
- `_build_chat_message(msg, fallback_index)` — `api/routers/chat/citations.py:105`
- `execute_chat` — `api/routers/chat/execute.py:26` (invoke :68, `await session.save()` :78, return :84)
- `ExecuteChatResponse` :139, `ChatMessage` :77, `MediaItem` :68 — `api/routers/chat/schemas.py`
- Session schemas `CreateSessionRequest`/`UpdateSessionRequest`/`ChatSessionResponse` — `api/routers/chat/schemas.py:6,23,96`;
  `get_sessions` `sessions.py:26`, `create_session` :59, `get_session` :94, `update_session` :133
- `POST /chat/media` + `GET /chat/media/{filename}` + `CHAT_MEDIA_FOLDER` + `save_uploaded_file`/`resolve_within` — `api/routers/chat/media.py`
- `@command`/`submit_command`/`get_command_status` — `commands/podcast_commands.py:51-72`,
  `api/podcast_service.py:95-133` (submit :96 → returns `RecordID`, `str(...)` it; status :118),
  `api/routers/commands.py:74-85`; worker auto-discovers `commands/` via `--import-modules commands`
- `ObjectModel` base + repo fns — `open_notebook/domain/base.py:31-237`, `open_notebook/database/repository.py`
- `Notebook` model — `open_notebook/domain/notebook.py:16-24`; `ChatSession` — `:683-696`
  (`nullable_fields` is `ClassVar[set[str]]` = `{"model_override","parent_session_id","quote"}`)
- notebook table schema `migrations/1.surrealql:44-52` (`archived option<bool> DEFAULT False` :47);
  flexible-object precedent `migrations/17.surrealql` (`chat_tag_colors`)
- async_migrate up list ends at 17 — `async_migrate.py:127-129`; `from_file` entries :165-180; down ~:182
- FE hook: `buildContext` — `useBuildNotebookContext.ts:26` (pure callback); imported by `useNotebookChat.ts:50`;
  `patchSessionMessages` `useNotebookChat.ts:136`, `sendMessageTo` :152 (cached-session read :175-177,
  `buildContext()` call :191), return object :235-267;
  `createSubChat` `useNotebookChatSessions.ts:164`, `createSidePanel` :188, `setSessionModelOverride` :260;
  token-count effect `useBuildNotebookContext.ts:58-85`
- FE query keys `query-client.ts:41-42` (`notebookChatSession(sessionId)`, `notebookChatSessions(notebookId)`)
- FE markdown: `AIMessageContent` + react-markdown `components` map `components/source/chat/ChatPanel.tsx`;
  `components/source/chat/MarkdownCodeBlock.tsx` (`extractLanguage`/`extractText`); `components/source/chat/MessageMedia.tsx`
- FE job-poll: reuse `use-jobs-poller.ts` (background-jobs Track B1) — register illustration jobs in `useJobsStore` (kind `'illustration'`); poller invalidates session on completion. Do NOT build a second `setInterval` loop.
- FE types `lib/types/api.ts` (`MediaItem` 165-170, `NotebookChatMessage` 255-270);
  `chatApi`/`notebooksApi` `lib/api/chat.ts`,`lib/api/notebooks.ts`
- FE context UI: `ContextToggle.tsx`, `source-context.ts` (`applyBulkSourceContext`/`applyBulkNoteContext`/
  `bulkModeForSource`); `components/notebooks/chat/PoppedChatPanel.tsx` (header row, has `notebookId`+`session`+`chat`);
  `components/notebooks/workspace/DeepDiveWorkspace.tsx` (`useNotebookWorkspaceStrict()` exposes `sources`/`notes`; renders `PoppedChatPanel`)
- FE toggle precedent: `components/notebooks/chat/SideChatDefaultMenu.tsx`;
  `components/notebooks/workspace/NotebookWorkspaceProvider.tsx` `chat_tag_colors`
  update+cache path (`notebooksApi.update` + `queryClient.setQueryData(QUERY_KEYS.notebook(id), …)`)

## Completion & archival
When the last chunk (likely **W3** or **F5**) is ☑, append a final Changelog line and move the whole dir
to `.claude/plans/archived/chat-foundation/`
(`mkdir -p .claude/plans/archived && mv .claude/plans/chat-foundation .claude/plans/archived/`). At that
point also remove the two superseded source dirs (`.claude/plans/auto-illustrate-chat`,
`.claude/plans/per-chat-context`) and the loose `.claude/plans/shimmering-fluttering-candle.md` if present.

## Changelog (cross-track)
- _(2026-06-26)_ Re-anchored all plan docs to post-refactor codebase: chat router split `api/routers/chat.py` → `api/routers/chat/` package; components reorganized into `chat/` + `workspace/` subfolders; hook line numbers updated for `useNotebookChat`/`useNotebookChatSessions`/`useBuildNotebookContext` split. Baked two background-jobs async compat fixes: B5 illustration trigger moved to worker `chat-completion` command (Track C2), not `execute_chat`; F3 must reuse `use-jobs-poller.ts` (Track B1) instead of a second poll loop. [P2 ☑]

## Open Questions (defaults chosen; surface if they bite)
- **S-gate (B7, needs-user)** — image build (W2/W3) proceeds only on GO / GO-WITH-ADJUSTMENTS. If NO-GO,
  mark W2/W3 ⊘ deferred; diagram mode still ships.
- **Q-R5 (perf)** — end-to-end job latency + GPU contention on the single qwen3.6. *Default: cap candidates
  top-K≈3; measure in W; reconsider deferred pre-filters only if it hurts.*
- **Q-mediaauth** — `GET /api/chat/media/{file}` has no auth. *Default: accept for local single-user; flag
  for any future multi-user.*
- **Q-A-downsyntax** — exact `REMOVE`/redefine style for `18_down.surrealql`. *Default: match existing
  `*_down.surrealql` files.*
- **Q-modelid** — exact qwen3.6 record id for `provision_langchain_model`. *Default: look up at build.*
