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
5. **Stable AI message id** — every AI message carries a real `.id` (`ai-{uuid4().hex}`, assigned at
   `graphs/chat.py:178`, persists in the checkpoint). `/chat/execute` is now a **202 job submit**
   (background-jobs), so the id reaches clients via `GET /chat/sessions/{id}`; the worker correlates
   **in-process** — `chat_completion_command` holds the graph invoke result and reads the new AI
   message's `.id` directly (no HTTP round-trip).
6. **Illustration job delivery (v2 — revised 2026-07-02 for the 202-async chat contract).** There is
   **NO illustration field on any API response** (the old `ExecuteChatResponse.illustration_job_id`
   is DEAD — the 202 ack is returned before the worker runs, so the API can never know the id).
   Instead:
   - **Trigger (W1, in `commands/chat_commands.py`):** after a successful graph run + `session.save()`,
     when `kind == "notebook"` AND the notebook's `auto_illustrate ?? true` AND an AI message was
     produced, `chat_completion_command` submits `illustrate_message` **fire-and-forget, BEFORE
     returning** (so the active-jobs poller never sees an empty active window between the chat job
     completing and the illustration job appearing). Trigger failures are swallowed (log + continue —
     never fail the chat job).
   - **Pinned args:** `{session_id, message_id, notebook_id, model_id, label}` (`label` feeds the
     background-jobs tray, mirroring `ChatCompletionInput.label`).
   - **Frontend discovery (F3):** no id hand-off needed — `use-jobs-poller.ts` already auto-registers
     unseen active jobs (`use-jobs-poller.ts:146`). F3 extends `deriveKind` (`'illustrate_message'` →
     kind `'illustration'`, union extended in `jobs-store.ts`) and `handleTermination` (kind
     `'illustration'` + `sessionId` → invalidate `notebookChatSession(sessionId)`). Illustration jobs
     are **silent**: no completion/failure toast (progressive enhancement), tray display only.
7. **Job output (`CommandOutput`)** — `{ success, mode, message_id, error_message?, processing_time }`.
   Frontend only needs terminal status; on success it **invalidates the session query** (P-4) and the
   merged illustration hydrates from the backend (single source of truth).
8. **i18n key namespaces (collision-free locale edits):** FE-POPOVER owns `chat.context*`
   (`contextForThisChat`, `resetToNotebookDefault`, `inheritingNotebookDefault`, `contextIncludedCount`);
   FE-TOGGLE owns `chat.autoIllustrate*` (`autoIllustrate`, `autoIllustrateHelper`); USAGE-FE (N3) owns
   `chat.contextMeter*`. Disjoint keys → clean worktree merge across `frontend/src/lib/locales/*`.
9. **Per-message usage (N2↔N3 interface, added 2026-07-05):**
   `ChatMessage.usage = { input_tokens?, output_tokens?, cache_read_input_tokens?,
   cache_creation_input_tokens?, model?, context_window? }` — all optional; ints except `model`
   (string). Rides `AIMessage.additional_kwargs["usage"]` through the LangGraph checkpoint (the exact
   plumbing `tool_uses` uses); the `usage` key is OMITTED at the checkpoint when the SDK reports
   nothing, and `context_window` is resolved only at session-read time via
   `open_notebook/ai/context_windows.py:get_context_window(model)` (claude-* → 200 000,
   qwen3.6 → 262 144, unknown → None → meter hides). Esperanto messages serialize `usage: null`.

## Global status table (orchestrator owns this)
Chunk ids are stable. **Owns (files)** is the conflict key; **Depends-on** drives wave computation.

| Chunk | Lane | Area file | Title | Owns (files) | Depends-on | Status |
|------:|------|-----------|-------|--------------|------------|--------|
| P1 | PRE | — | Background-jobs plan prerequisite (chat-foundation runs after background-jobs lands) | cross-plan gate only | — | ☐ |
| P2 | PRE | — | Re-anchor plan docs + async compat fixes (post-refactor paths + B5/F3 compat bakes) | `coordinator.md`, `backend.md`, `frontend.md`, `worker.md` | — | ☑ |
| B1 | MIG | backend.md | Migration 18 (all 3 schema changes) + register | `migrations/18.surrealql`, `18_down.surrealql`, `database/async_migrate.py` | — | ☑ (454d328 — appended at END, positional v21; applied live + schema verified) |
| B2 | MODELS | backend.md | Domain models: `ChatMessageMedia` + `Notebook.auto_illustrate` + `ChatSession.context_config` | `open_notebook/domain/notebook.py` | B1 | ☑ (8cc887e — live save/read round-trip OK; test_domain 32 pass. Anchors stale: Notebook :70, ChatSession :970) |
| B3 | MSGID | backend.md | Stable AIMessage `.id` (checkpoint-persistent) | `open_notebook/graphs/chat.py` | — | ☑ (454d328 + **repair e2755a3**: the `or` fallback never fired — providers supply ids (lc_run--*/UUIDs), so no real message ever got the `ai-` prefix (DG-W1-A, found by W1). Now forces `ai-` unless already prefixed; live-verified `ai-f9b712e5…`) |
| B4 | CTX-CRUD | backend.md | `context_config` on session schemas + create/update/get | `api/routers/chat/schemas.py` + `api/routers/chat/sessions.py` | B2 | ☑ (fddc233 — live round-trip verified: create/GET/PUT-populated/PUT-null-clears) |
| B5 | HYDRATE | backend.md | Hydrate-merge sidecar into session reads (per-message lookup in `_build_chat_message`) | `api/routers/chat/citations.py` | B2, B3 | ☑ (6fa41b0 — merge logic mock-verified all modes + degrade; sidecar persistence verified live post mig-18 repair 633eeea; fence-in-session e2e rides W1 verify) |
| B6 | NB-API | backend.md | `auto_illustrate` passthrough on notebook-update | `api/routers/notebooks.py`, `api/models.py` | B2 | ☑ (5328ed5 — live verified: PUT false persists, reads back, reset true) |
| B7 | SPIKES | worker.md | R3 vision + R4 relevance spikes → **S-gate** | scratch scripts only | — | ☑ (ad9d70a — report.json). **S-gate BLESSED GO-WITH-ADJUSTMENTS by user 2026-07-04**: τ=0.6, top-K=3, PageImages-first + early-exit, heavy-lane mandatory (P-6). W2/W3 UNBLOCKED. SSRF/safety review mode (user-chosen): orchestrator adversarial review of the landed W1–W3 diff + user final sign-off on the end punch-list. |
| W1 | WORKER | worker.md | Enrichment command: trigger (in `chat_completion`) → gate → route → **diagram** → sidecar | `commands/illustrate_commands.py`, `open_notebook/graphs/illustrate.py`, `prompts/illustrate/`, `commands/chat_commands.py` (trigger) | B2, B3, B5 | ☑ (01633fc + orchestrator repair e2755a3 for DG-W1-A. **Live e2e PASS**: real chat turn → trigger → gate ON → GPU sequenceDiagram → sidecar → mermaid fence hydrated in session @106s; toggle-OFF turn submits no illustrate job) |
| W2 | WORKER | worker.md | **Image** pipeline: expand → search → VLM relevance/abstain | (same as W1) | W1, **B7 (S-gate GO)** | ☑ (11d8898 — in-process verify: Rosetta Stone → PageImages EARLY-EXIT, conf 1.00 chosen; abstract subject → deliberate ABSTAIN; τ=0.6/top-K=3 honored; +gate-503 backoff retry shared with W1 path. W3 seam stub declines → mode='none' until W3) |
| W3 | WORKER | worker.md | **Image** safety (fail-closed) + SSRF fetch → WebP → store → sidecar | (same as W1) | W2 | ☑ (5edf9f1 + **security fix 031099e**). Live image e2e PASS. **`to-fix/002` ✅ FIXED**: single SSRF-guarded fetch feeds both the safety judge and the store (kills HIGH judge-fetch SSRF + MED-HIGH bait-and-switch); offline SSRF matrix 32/32 both paths + re-run live e2e (guarded relevance judge → 1 guarded fetch → qwen3.6-VL SAFE → WebP 329KB → served 200/image-webp, no regression). **W2/W3 security-clean; only user final sign-off remains (punch-list).** |
| F1 | FE-TYPES | frontend.md | Types + chat-api passthrough (`context_config`, `auto_illustrate`) | `frontend/src/lib/types/api.ts`, `frontend/src/lib/api/chat.ts` | — | ☑ (454d328 — done by orchestrator on HEAD; chat.ts passes full body, no change needed) |
| F2 | FE-HOOK | frontend.md | `useNotebookChat`: per-session context resolution + quote-only seed + setter | `frontend/src/lib/hooks/useNotebookChat.ts` (+ `useBuildNotebookContext.ts` buildContextFor extraction, `useNotebookChatSessions.ts` seed+setter — authorized cross-file, disjoint from wave) | F1 | ☑ (8cc887e — tsc clean; setSessionContextConfig exported for F5) |
| F3 | FE-POLLER | frontend.md | Jobs poller: `'illustration'` kind → auto-register + session invalidate (silent, no toast) | `frontend/src/lib/stores/jobs-store.ts`, `frontend/src/lib/hooks/use-jobs-poller.ts` (+ `components/jobs/JobTrayItem.tsx` Wand2 icon — type-forced ripple, disjoint) | F1 | ☑ (8cc887e — tsc clean; silent on completion+failure; invalidates session query) |
| F4 | FE-MERMAID | frontend.md | Mermaid renderer (strict + DOMPurify + parse-or-fallback) | `components/source/chat/Mermaid.tsx` (new), `components/source/chat/MarkdownCodeBlock.tsx`, `components/source/chat/ChatPanel.tsx` | — | ☑ (454d328 — branched inside MarkdownCodeBlock; components map now in MessageList.tsx post-3537d09, so ChatPanel/MessageList untouched; tsc+build clean) |
| F5 | FE-POPOVER | frontend.md | Side-chat Context popover + i18n (`chat.context*`) | `components/notebooks/chat/PoppedChatPanel.tsx`, `components/notebooks/chat/SideChatContextPopover.tsx` (new), `components/notebooks/workspace/DeepDiveWorkspace.tsx`, `locales/*` | F1, F2 | ☑ (429dfea — tsc+eslint clean, 4 keys ×14 locales namespace-clean; visual e2e on punch-list) |
| F6 | FE-TOGGLE | frontend.md | Per-notebook auto-illustrate toggle + i18n (`chat.autoIllustrate*`) | `components/notebooks/chat/SideChatDefaultMenu.tsx`, `components/notebooks/chat/ChatDock.tsx`, `components/notebooks/workspace/NotebookWorkspaceProvider.tsx`, `locales/*` | F1 | ☑ (8cc887e — tsc+build clean; DropdownMenuCheckboxItem; 14 locales. Live-persist verify parked on B6/W1) |
| N0 | HOTFIX | backend.md | E2BIG hotfix: oversize system prompts via stdin transcript preamble | `open_notebook/ai/claude_agent.py`, `tests/test_claude_agent.py` | — | ☑ (520627c — landed live during the debugging session; guard `MAX_SYSTEM_PROMPT_ARG_BYTES` preserved by N1/N2) |
| N1 | AGENT-CTX | backend.md | Slim-index context on the Claude-agent path (Esperanto byte-identical; degrade-never-fail) | `open_notebook/graphs/chat.py`, `open_notebook/graphs/source_chat.py`, `tests/test_agent_context_index.py` (new) | N0 | ☑ (e4985ab — 22 new tests; live: slim log `51059B -> 5366B`, agent answered ch.6 via get_source_outline/search + cited source id; qwen turn routed Esperanto, no slim line) |
| N2 | USAGE-BE | backend.md | Capture Agent-SDK `ResultMessage.usage` + context-window map (contract #9) | `open_notebook/ai/claude_agent.py`, `open_notebook/ai/context_windows.py` (new), `api/routers/chat/schemas.py`, `api/routers/chat/citations.py`, `tests/test_claude_agent.py` | N0 | ☑ (994da2c — 9 new tests, 27 pass; live: `usage.input_tokens=8236`, `context_window=200000`, `model=claude-opus-4-8` on the agent message; Esperanto message `usage: null`) |
| N3 | USAGE-FE | frontend.md | Chat context-usage meter (exact fraction+bar / tilde estimate) + `chat.contextMeter*` i18n | `lib/types/api.ts`, `components/notebooks/chat/ContextUsageMeter.tsx` (new), `ChatDock.tsx`, `PoppedChatPanel.tsx`, `locales/*` | N2 (contract only — built in parallel) | ☑ (75ae0c3 — tsc+build clean; 7 keys × 14 locales; locale-parity vitest byte-identical failures to pre-existing baseline. Visual smoke parked on punch-list) |
| N4 | RESUME | backend.md | Layered SDK session resume (checkpoint stays source of truth) | — | N1, N2 measurements | ⊘ deferred — documented in backend.md; do NOT build ahead of N2 usage data |

Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

> **Same-file note (worktree-required):** B4 and B5 edit **different files** in the
> `api/routers/chat/` package (B4: `schemas.py` + `sessions.py`; B5: `citations.py` only), so there is
> no per-function file conflict — worktree isolation still applies for clean integration. F3 no longer
> touches `useNotebookChat.ts` (that was the v1 design) — it edits the two **background-jobs-owned**
> files (`jobs-store.ts`, `use-jobs-poller.ts`); this is safe because ALL background-jobs chunks land
> before any chat-foundation chunk starts (meta-coordinator lane rule — bg B3 also edits
> `use-jobs-poller.ts` and must be ☑ first). W1 extends `commands/chat_commands.py` (bg Track A file) —
> same lane rule applies.

## Computed waves (what the orchestrator will schedule)
- **Wave 1 (5 parallel):** B1, B3, B7, F1, F4 — all dep-free; each self-verifies (B1 applies the migration).
- **Wave 2 (3 parallel):** B2 (B1✓), F2 (F1✓), F6 (F1✓).
- **Wave 3 (5 parallel):** B4 (B2✓), B5 (B2,B3✓), B6 (B2✓), F3 (F1✓), F5 (F2✓).
- **Wave 4:** W1 (B2,B3,B5✓).  **Wave 5:** W2 (W1✓ + S-gate GO).  **Wave 6:** W3 (W2✓).
- **Wave 7 (N-lane hotfix, 2026-07-05):** N0 — E2BIG stdin reroute, landed inline during the live
  debugging session.  **Wave 8 (3 parallel):** N1, N2, N3 (N3 built against frozen contract #9 in
  parallel with N2; runtime verify honored the dep post-integration). N4 stays ⊘.
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
| G-transport | Which chat illustrates | **Notebook chat only** in v1 (`kind == "notebook"` guard in the trigger). Source chat deferred for scope — note it now rides the SAME job rails (bg C3 killed SSE), so extending later is a small guard change, not a transport rework. |
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
| P-5 | Illustration delivery post-202 (2026-07-02) | **v2 contract** (frozen contract #6): trigger lives in `chat_completion_command` (W1 owns the edit — the old plan pointed at bg Track C2, which landed as a pure FE refactor and never owned it); FE discovery via the poller's existing auto-register of unseen active jobs. `ExecuteChatResponse.illustration_job_id` DROPPED (202 ack predates the worker run — the field was unpopulatable). |
| P-6 | GPU contention (illustration vs interactive chat) | Enrichment LLM/VLM calls in `graphs/illustrate.py` **acquire `heavy_lane`** (via `is_heavy_model(model_id)` from `commands/_heavy_lane.py`) — qwen3.6 is local/heavy, so illustration serializes BEHIND interactive chat turns on the single GPU instead of contending. Enrichment is background enhancement; queuing is acceptable (Q-R5 latency measured in W1/W2). The ds4↔Ollama admission gate (:11435) remains the infra-level backstop. |

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
- FE job-poll: reuse `use-jobs-poller.ts` (background-jobs Track B1) — the poller **auto-registers unseen active jobs** (`use-jobs-poller.ts:146`), so no id hand-off is needed; F3 extends `deriveKind` (`'illustrate_message'` → `'illustration'`) + `handleTermination` (invalidate session, NO toast) + the `JobKind` union in `jobs-store.ts`. Do NOT build a second `setInterval` loop.
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
- _(2026-07-06)_ **🏁 ARCHIVED — chat-foundation closed out.** All 16 chunks ☑ + N-lane N0–N3 ☑ (N4
  `⊘ deferred` backlog). `to-fix/002` SSRF fixed (`031099e`); W2/W3 orchestrator-security-signed-off.
  **Handed to the user as individual follow-ups** (per the cross-plan finish instruction): the visual
  browser smokes + the user's final SSRF sign-off. Final merged-tree verify green (backend 32 + baseline
  flake; frontend `tsc` exit 0). Directory archived to `archived/chat-foundation/`.
- _(2026-07-05)_ **N-lane landed: N0 ☑ (520627c), N1 ☑ (e4985ab), N2 ☑ (994da2c), N3 ☑ (75ae0c3); N4 ⊘.**
  Root cause: a claude-agent chat with a book-sized context died with `[Errno 7] Argument list too long`
  (system prompt passed as ONE exec arg; Linux caps a single arg at 128 KiB). N0 hotfix reroutes >100KB
  prompts via stdin. N1 replaces the pushed context blob with a slim source/note index on the agent path
  ONLY (MCP tools fetch on demand; Esperanto byte-identical; any index-build failure degrades to the old
  blob). N2 captures `ResultMessage.usage` → `additional_kwargs["usage"]` → `ChatMessage.usage` per NEW
  frozen contract #9 + `context_windows.py` map. N3 renders the dock/side-chat context meter (exact
  fraction + tone bar when usage present; tilde chars/4 estimate otherwise; 7 `chat.contextMeter*` keys ×
  14 locales). Run as 3 parallel worktree agents (relaunch — the first attempt's session died pre-work;
  stale worktrees cleaned), clean disjoint merges (9da0412/d5b9d1b/e8dbccc), merged-tree verify green
  (61 backend tests, tsc, build). **Live e2e PASS on the ML-book notebook:** claude-agent turn → worker
  log `slim context: system prompt 51059B -> 5366B` (before is ~51KB not the historical 100KB+ because
  doc-foundation tiered summaries already shrank full-content renders), reply answered ch.6/decision-trees
  via `get_source_outline`+`search` with 5 tool_uses and cited the source id; session read shows
  `usage {input_tokens: 8236, output_tokens: 1508, cache_*, model: claude-opus-4-8, context_window:
  200000}`. qwen3.6 turn routed Esperanto (no slim line, blob path unchanged) with `usage: null`.
  **Observations:** (a) first qwen turn after idle failed transiently ("provider temporarily
  unavailable") during the heavy-slot transition + 35B cold load — the chat retry budget gives up faster
  than verify-clean's (c8932a1 fixed this for summaries only); warm retry fine; pre-existing, not
  N-lane. (b) one warm qwen reply came back empty (think-strip artifact, known quirk, next turn fine).
  (c) cheap source/note listings carry no abstract field, so the N1 index is titles-only in practice
  (abstract hook dormant by design — no per-source round-trips). **Punch-list:** visual meter smoke
  (dock exact fraction + side-chat tilde estimate).
- _(2026-07-04, security fix)_ **`to-fix/002` ✅ FIXED (031099e) — W2/W3 now security-clean.** The
  orchestrator's adversarial review had flagged two real findings on the landed W3 diff; both are closed by
  one change in `graphs/illustrate.py`: (1) HIGH — the relevance/safety *judge* fetch
  (`_fetch_image_data_uri`) had its own unguarded `follow_redirects=True` path (no SSRF validation, no IP
  pin) → blind SSRF to localhost/metadata; it now **delegates to `_ssrf_guarded_fetch`** and Pillow-decode-
  gates the bytes before the VLM. (2) MED-HIGH — `_fetch_and_store_image` fetched *twice* (judge bytes vs
  stored bytes), so a stateful origin could bait-and-switch past the safety judge; it now **fetches once**
  and the safety judge + WebP encode both operate on those exact bytes. `_decode_reencode_webp` returns
  `(webp, source_mime)`. **Verify: offline SSRF matrix 32/32 against BOTH the judge and storage paths**
  (127.0.0.1, 169.254.169.254, localhost, `::1`, `::ffff:127.0.0.1`, decimal/octal/hex IPs, private ranges,
  non-http scheme, redirect-to-private rejected per-hop, redirect public→public succeeds, IP-pin assertion,
  15MB/10MB byte caps, Pillow gate on non-image bytes, single-fetch assertion, unsafe→abstain) **+ a live
  image e2e** (real "Rosetta Stone" turn → PageImages → guarded relevance judge conf 1.00 early-exit → one
  guarded storage fetch → qwen3.6-VL safety SAFE → WebP 329KB stored → served `GET /api/chat/media/…webp`
  200/image-webp — byte-identical size to the pre-fix run, no regression). Also confirmed the LOW-MED note:
  `media.label` renders only via React-escaped `alt=`/`{…}` in `MessageMedia.tsx` (never
  `dangerouslySetInnerHTML`; the one such call is Mermaid.tsx on the DOMPurify-sanitized SVG). **W2/W3 are
  now security-signed-off by the orchestrator; the user's final sign-off is the only remaining item (end
  punch-list). This was the #1 remaining code item — chat-foundation is now fully code-complete.**
- _(2026-07-04)_ **W3 landed (5edf9f1) — image path code-complete + LIVE image e2e PASS.** Real chat turn
  ("Tell me about the Rosetta Stone") → gate routed IMAGE → PageImages → qwen3.6-VL safety judge SAFE
  (46.8s) → SSRF-guarded pinned fetch → WebP re-encode (329KB) → stored + served `GET /api/chat/media/
  <sha256>.webp` 200/image-webp → hydrated into `.media` of the AI message. W3 offline verify 21/21
  (SSRF negatives, byte-cap, non-image, redirect-to-private, fail-closed safety, dedupe). **Orchestrator
  adversarial security review verdict = SIGN-OFF-WITH-NOTES → effectively BLOCK on 2 real findings
  (`to-fix/002`):** (1) HIGH — the *judge/relevance* fetch `_fetch_image_data_uri` has NONE of the SSRF
  guard the storage fetch has (no validation on relevance candidates, follows redirects unrevalidated, no
  IP pin) → blind SSRF to localhost/metadata; (2) MED-HIGH — safety judges one fetch but storage does a
  *separate* fetch, stored bytes never re-judged (bait-and-switch). **Both fixed by one change:** route
  every image fetch through the guarded pinned fetcher, judge-and-store the SAME bytes once. **Until
  `to-fix/002` lands, W2/W3 are NOT security-signed-off** (diagram path W1 unaffected). The *storage*
  fetch, path-traversal, fail-closed direction, EXIF-strip all verified clean. **This is the #1 remaining
  code item** — everything else left is human punch-list (visual smokes) or the un-blocking b2/b3 book re-run.
- _(2026-07-04)_ **Waves 4–5 landed: W1 ☑ (01633fc + e2755a3), W2 ☑ (11d8898); T3-d (cross-plan tail) also in (bc44fbe).**
  **W1 live e2e PASS on the running stack:** real chat turn → 202 → worker → stable `ai-` id → trigger →
  gate ON → qwen3.6 sequenceDiagram (~2min heavy-lane) → sidecar `mode='diagram'` → B5 hydrate shows the
  ```mermaid fence in `GET /chat/sessions/{id}` at 106s; toggle-OFF turn submits NO illustrate job.
  **DG-W1-A (HIGH, found by W1's agent, fixed by orchestrator e2755a3):** B3's `ai_message.id or …` never
  assigned the `ai-` prefix on real providers — the whole illustration/hydrate chain keyed on it and would
  never have fired; now forced per contract #5. **W1 decisions:** gate max_tokens 2048 (qwen ignores
  /no_think — 1024 was all-<think> → empty), commands/__init__.py registration edit, lazy heavy-lane import
  (broke a real import cycle), `mode='none'` sidecar on definitive declines. **W2:** promotes the B7
  pipeline with S-gate adjustments — PageImages-first + early-exit (fired on "Rosetta Stone", conf 1.00),
  Commons+Openverse fallback, VLM rank+threshold with deliberate abstain verified on an abstract subject;
  adds bounded gate-503 backoff (ds4↔Ollama slot transitions) shared with the diagram path. Image path
  still resolves `mode='none'` until W3 fills the `_fetch_and_store_image` seam. Next: W3 (safety+SSRF) →
  orchestrator adversarial security review → live image e2e.
- _(2026-07-04)_ **Wave 3 landed: B4 ☑ (fddc233), B5 ☑ (6fa41b0), B6 ☑ (5328ed5), F5 ☑ (429dfea).** Run via
  `/chunk-plan-execute` (cross-plan finish run), 4 parallel worktree agents, all clean ff from 520627c —
  the baked-in stale-base guard held. Merged-tree verify green: backend 66+12 pass, imports clean, tsc
  clean (zero output), on-api/on-worker restart clean. **Live checks:** B4 full context_config round-trip
  (create → GET → PUT populated → PUT null clears) and B6 auto_illustrate PUT-false-persists both PASS
  against the running API. **⚠ Critical seam fix (633eeea):** B5's agent discovered migration 18's inline
  `--` comment on the `mode` line silently swallowed the `media`/`diagram`/`created` DEFINEs + the UNIQUE
  index (AsyncMigration.from_file flattens to one line → everything after the first inline comment became
  comment). Confirmed live via INFO FOR TABLE (only 3 of 6 fields existed despite "applied v21"). File
  fixed for fresh inits; missing DEFINEs re-applied idempotently to the live DB; ChatMessageMedia
  round-trip now persists diagram + created (also explains/closes Wave-1's "created returned None"
  follow-up). **Lesson: never put trailing `--` comments in *.surrealql — from_file eats the rest of the
  migration.** Repo-wide scan: no other migration affected. B5 e2e (fence in session read) + F5 visual
  e2e ride W1's verify / the punch-list. S-gate blessed this session → Wave 4 = W1, then W2→W3.
- _(2026-07-04)_ **Wave 2 landed (8cc887e): B2 ☑, F2 ☑, F3 ☑, F6 ☑ + B7 spike ☑.** Run via `/chunk-plan-execute`
  (5 parallel agents: 4 worktree chunks + the B7 GPU spike, no worktree). All 4 worktree agents hit the stale-base
  trap (seeded at `a6e0c3f`, 3 behind HEAD) and self-corrected via `git merge --ff-only feature/multipanelchat` —
  the baked-in first-step guard worked every time. Integrated by file-copy (fully disjoint: 1 backend + 23 frontend
  files). Merged-tree verify green: `tsc --noEmit` clean, `test_domain` 32 pass, on-api/on-worker restart clean.
  **B2**: `ChatMessageMedia` + `Notebook.auto_illustrate` + `ChatSession.context_config` (live save/read OK; plan
  anchors were stale — Notebook :70, ChatSession :970). **F2**: `sendMessageTo` per-session context resolution +
  `buildContextFor` extraction (in `useBuildNotebookContext.ts`) + quote-only seed + `setSessionContextConfig`
  setter (in `useNotebookChatSessions.ts` — authorized cross-file, disjoint from wave; F5 consumes the setter).
  **F3**: `JobKind 'illustration'` → `deriveKind` + silent session-invalidate (+ `JobTrayItem` Wand2 icon, type-forced
  ripple). **F6**: dock-header auto-illustrate toggle (`DropdownMenuCheckboxItem`) + `chat.autoIllustrate*` in 14
  locales. **B7 spike (ad9d70a → report.json): GO-WITH-ADJUSTMENTS.** qwen3.6:35b vision nailed all R3 probes
  (TP/TN conf 1.0, safety judge works); R4 chose a relevant image for all 5 subjects (concrete + abstract),
  correctly rejecting wrong candidates; all 3 sources (PageImages/Commons/Openverse) reachable. **Adjustments for
  W2/W3:** PageImages-first + early-exit (won 4/5), τ=0.6, top-K=3; **headline caveat = latency** (~30–48s per VLM
  call → 76–139s end-to-end per illustration on the single GPU → heavy-lane serialization P-6 is mandatory);
  set `max_tokens` explicitly (one candidate parse-failed, degraded gracefully). **S-gate awaits user bless.**
  **Two follow-ups filed:** (a) `jobs.kind.illustration` has no locale entry (repo locale-parity vitest already
  failing pre-existing — non-EN locales miss the whole `jobs.kind.*` block; fallback key unreachable since
  illustration jobs always carry a `label`); (b) `JobTrayItem`/`useBuildNotebookContext`/`useNotebookChatSessions`
  cross-file edits landed outside their chunk's nominal Owns row (all type-forced or plan-authorized, all disjoint).
  **Lesson:** under Next 16 **Turbopack**, a *symlinked* `node_modules` breaks `npm run build` ("points out of
  filesystem root") — F6 worked around with `cp -al`; Wave-3 dispatch prompts switched to `cp -al` for build chunks.
- _(2026-07-04)_ **Wave 1 landed (454d328): B1 ☑, B3 ☑, F1 ☑, F4 ☑; B7 ◐ (spike running).**
  Run via `/chunk-plan-execute` (cross-plan orchestration, Lane A #2). Migration 18 appended at the END
  of both async_migrate lists (positional DB v21 — the "18" filename is a label; DB was at v20) and
  applied live + schema-verified (`chat_message_media` insert/read OK, `context_config`/`auto_illustrate`
  selectable). **Stale-base hazard hit again:** all 5 worktree agents seeded from `a6e0c3f` (3 commits
  behind HEAD, pre-tool-loop `3537d09`). Integrated by selective file-copy for non-colliding files
  (async_migrate, MarkdownCodeBlock, package.json/lock — identical since a6e0c3f) and **hand-applied B3**
  onto the current 309-line `chat.py:284` (the plan's `:178` + the worktree's `:186` were both stale;
  a decoy `model_copy` at :188 in the tool loop was avoided). **F1 was redone by the orchestrator on HEAD**
  (its worktree agent no-op'd with 0 tool-uses; `api.ts` is a collision file). F4 discovered the
  ReactMarkdown components map moved `ChatPanel.tsx`→`MessageList.tsx` (3537d09) and branched inside
  `MarkdownCodeBlock` — kept the ChatPanel/MessageList files untouched. Verify: `test_domain` 32 pass, tsc
  clean, mermaid@11.16 + dompurify@3.4.11 installed. **Lesson (re)confirmed:** every worktree agent must
  `git merge --ff-only feature/multipanelchat` FIRST — baked into Wave 2+ dispatch prompts. Minor follow-up:
  `chat_message_media.created` returned `None` on a raw SurrealQL insert (domain model sets it on save, so
  non-blocking).
- _(2026-07-02)_ **Design revision: illustration delivery v2** (frozen contracts #5/#6 rewritten; decisions
  P-5/P-6 added). The v1 contract predated the 202-async chat pivot and was unimplementable:
  `ExecuteChatResponse.illustration_job_id` can't be populated (the 202 ack returns before the worker
  runs), and the trigger was assigned to bg Track C2, which landed as a pure FE refactor — the
  worker-side trigger had **no owner**. Fixes: trigger now owned by **W1** (edits `commands/chat_commands.py`,
  submits `illustrate_message` before the chat job returns); FE discovery via the poller's existing
  auto-register (F3 re-scoped to `jobs-store.ts` + `use-jobs-poller.ts`, silent kind, dep on F2 dropped);
  B5 slimmed to `citations.py`-only hydrate (per-message `get_for_message` lookup inside the already-async
  `_build_chat_message` — no batching, no `execute.py`/`schemas.py` edits); B3/F1 drop the dead field;
  heavy-lane serialization made an explicit decision (P-6). Chunk specs updated in backend.md /
  frontend.md / worker.md. Wave shape unchanged (W1 deps grew but it was already Wave 4).
- _(2026-06-26)_ Re-anchored all plan docs to post-refactor codebase: chat router split `api/routers/chat.py` → `api/routers/chat/` package; components reorganized into `chat/` + `workspace/` subfolders; hook line numbers updated for `useNotebookChat`/`useNotebookChatSessions`/`useBuildNotebookContext` split. Baked two background-jobs async compat fixes: B5 illustration trigger moved to worker `chat-completion` command (Track C2), not `execute_chat`; F3 must reuse `use-jobs-poller.ts` (Track B1) instead of a second poll loop. [P2 ☑]

## Open Questions (defaults chosen; surface if they bite)
- ~~**S-gate (B7, needs-user)**~~ — **RESOLVED 2026-07-04: user blessed GO-WITH-ADJUSTMENTS** (τ=0.6,
  top-K=3, PageImages-first + early-exit). W2/W3 proceed. SSRF/safety human gate satisfied via
  orchestrator adversarial review + user sign-off parked on the end punch-list.
- **Q-R5 (perf)** — end-to-end job latency + GPU contention on the single qwen3.6. *Default: cap candidates
  top-K≈3; measure in W; reconsider deferred pre-filters only if it hurts.*
- **Q-mediaauth** — `GET /api/chat/media/{file}` has no auth. *Default: accept for local single-user; flag
  for any future multi-user.*
- **Q-A-downsyntax** — exact `REMOVE`/redefine style for `18_down.surrealql`. *Default: match existing
  `*_down.surrealql` files.*
- **Q-modelid** — exact qwen3.6 record id for `provision_langchain_model`. *Default: look up at build.*
