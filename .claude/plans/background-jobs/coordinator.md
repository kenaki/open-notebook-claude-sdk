# Background Processes for Local-Model Work — Coordinator / Index

> **Shared source of truth for a multi-track plan.** Holds everything common to all tracks.
> Each track is executed from its own file (`<track>.md` in this directory) by its own chat.
> A track chat reads THIS file first, then owns exactly one track file.
> Full design rationale lives beside this in **[design.md](design.md)** (the approved plan-mode doc).
> **Location:** `.claude/plans/background-jobs/coordinator.md` → the whole directory is archived to
> `.claude/plans/archived/background-jobs/` once every track is ☑.

## How to run this plan (read first)
1. Pick a track whose deps are ☑ in the Global status table and whose row is **runnable now**.
2. Open its file `<track>.md` in a fresh chat; that file is self-contained (+ this coordinator).
3. You may run every **concurrent** track (see the matrix) at the same time in separate chats.
4. One chunk per session. On each chunk completion, update BOTH the track file's status AND the Global
   status table here, then announce "safe to clear context" and stop.

> **⚠️ Isolate parallel chats.** Two concurrent track-chats must NOT share one checkout on one branch —
> they clobber each other's git state even with disjoint files. Give each its own git **worktree**
> (or branch) off `feature/multipanelchat`, and merge at the end. (`chunk-plan-execute` does this for you.)

## Run a track in a fresh chat (copy a prompt)
Each prompt is **re-runnable** — paste the same one on first run and on every resume after `/clear`; it
self-locates from the Status table + `git log`. (Authoritative copy lives in each track file's SESSION HANDOFF.)
- **Track A — Foundation:** "Continue Background-Jobs Track A. Read `.claude/plans/background-jobs/coordinator.md` then `a-foundation.md`; derive the next unstarted chunk from the Status table + git log; do ONE chunk, verify, commit (one chunk = one commit), update both status tables; touch only Track A's files; announce safe-to-clear and stop."
- **Track B — Jobs runtime/tray:** same, swapping in `b-jobs-runtime.md` and Track B's files. **Confirm A4 + A5 are ☑ first.**
- **Track C — Chat surfaces:** same, swapping in `c-chat-surfaces.md`. **C1 is dep-free; C2 needs A2+A5, C3 needs A3+A5.**
- **Track D — i18n:** same, swapping in `d-i18n.md`. **Confirm B and C are ☑ first.**

## Concurrency matrix
| Track | File | Depends on (must be ☑) | Concurrent with | Sequential after | Why |
|-------|------|------------------------|-----------------|------------------|-----|
| A — Foundation | `a-foundation.md` | — | C (and B once A4/A5 land) | — | backend + shared store; disjoint from C's frontend files |
| B — Jobs runtime/tray | `b-jobs-runtime.md` | A4 (status API), A5 (store) | C | A | poller/tray consume the store + commands API |
| C — Chat surfaces | `c-chat-surfaces.md` | C1: none · C2: A2+A5 · C3: A3+A5 | A, B | (per-chunk) | edits chat hooks/components; disjoint from A & B files |
| D — i18n | `d-i18n.md` | B ☑, C ☑ | — | B, C | needs final `jobs.*` key names used by B & C |
> Read as: **A ‖ C** from the start; **B** joins (‖ C) once A4+A5 are ☑; **D** last.

## Shared-file ownership (conflict map)
| File | Owning track | Other tracks must wait / not touch | Note |
|------|--------------|------------------------------------|------|
| `frontend/src/app/(dashboard)/layout.tsx` | **B** | A/C/D never touch it | B1 mounts `<JobsRuntime/>`, B2 mounts `<JobTray/>` |
| `frontend/src/components/source/chat/ChatPanel.tsx` | **C** | B never touches it | C1 adds the pending/error bubble (shared by notebook + source) |
| `frontend/src/lib/stores/jobs-store.ts` | **A** (A5 creates) | B & C **import** it, never edit | full store interface defined in A5 to satisfy B + C |
| `frontend/src/lib/api/chat.ts`, `lib/types/api.ts` | **A** (A2) | C consumes `chatApi.sendMessage`, never edits | 202 `{job_id}` return type |
| `frontend/src/lib/api/commands.ts` | **A** (A4 creates) | B imports, never edits | `commandsApi.listActive/getJob` |
| `commands/*`, `open_notebook/graphs/{chat,source_chat}.py`, `api/routers/chat/` (package: execute.py + schemas.py), `api/routers/source_chat.py`, `api/source_chat_service.py`, `api/command_service.py`, `api/routers/commands.py` | **A** | B/C/D never touch | backend foundation |

## Global status table
| Track | Chunk | Title | Status | Owner / session | Notes |
|-------|------:|-------|--------|-----------------|-------|
| A | 1 | chat_completion command + heavy-lane + WAL + register | ☑ done | main session | verified committed (bundled in 827bf48) |
| A | 2 | `/chat/execute` → 202 submit (+ chat.ts/api types) | ☑ done | main session | commit bbce67b; tsc+pytest green |
| A | 3 | source_chat send → 202 submit | ☑ done | wave1 2026-06-29 | commit 1ef7325; POST→202 verified in openapi |
| A | 4 | status API: `list_command_jobs` active + `commands.ts` client | ☑ done | wave1 2026-06-29 | commit 484ef18; SQL runs, GET /commands/active→200 |
| A | 5 | shared `jobs-store.ts` (Zustand + persist) | ☑ done | wave1 2026-06-29 | commit 831aede; tsc clean. **Track B fully unblocked** |
| B | 1 | `use-jobs-poller` + `JobsRuntime` + mount | ☑ done | wave3 2026-06-29 | commit 82257ae; use-jobs-poller.ts (237L) + JobsRuntime + layout mount |
| B | 2 | `JobTray` + `JobTrayItem` + `JobStatusBadge` + mount | ☐ todo | | dep B1 ✓ |
| B | 3 | completion/failure toasts + `job-origin` helper | ☐ todo | | dep B1 ✓ |
| C | 1 | shared pending/error chat bubble + message types | ☑ done | worktree-bg-jobs-c1 | commit 3295a27; merged to feature/multipanelchat |
| C | 2 | notebook send/receive refactor | ☑ done | wave3 2026-06-29 | commit 5171514; useNotebookChat sendMessageTo → job submit + placeholder |
| C | 3 | source-chat → cache-backed + job-tracked | ☑ done | wave3 2026-06-29 | commit e9bcafe; cache-backed + job-tracked source chat (mirrors C2). tsc clean. ⚠ live-flow smoke pending |
| D | 1 | `jobs.*` i18n keys across 14 locales | ☐ todo | | dep B, C |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (cross-track)
- 2026-06-29 — Wave-3 completion: **C3 ☑ (e9bcafe)** source-chat moved off useState+SSE onto the
  TanStack cache + job model (mirrors C2); `source-chat.ts` send → 202 `{job_id,session_id}`, optimistic
  user msg + `source_chat` job register + `pending-<job_id>` placeholder, SSE reader deleted. Verified:
  frontend `tsc` clean (only pre-existing `@testing-library` test-file errors); B1 poller already
  invalidates `sourceChatSession(targetId,sessionId)` on completion (use-jobs-poller.ts:204). **Track C
  now fully ☑ (C1+C2+C3); Track A ☑.** Remaining: Track B B2/B3 (dep B1✓), Track D D1 (dep B,C).
- 2026-06-29 — Reconciliation (resumed orchestrator): **B1 ☑ (82257ae)** use-jobs-poller + JobsRuntime +
  layout mount; **C2 ☑ (5171514)** notebook send/receive refactor (sendMessageTo → 202 job submit +
  pending placeholder, store-derived sending in ChatDock/PoppedChatPanel). Both were committed by prior
  sessions but never recorded — now reflected in both status tables. **Next runnable: B2, B3 (dep B1 ✓)
  and C3 (dep A3/A5/C1 ✓).**
- 2026-06-25 — Plan authored from approved [design.md](design.md). Track A Chunk 1 already implemented in
  the main session (uncommitted on `feature/multipanelchat`): `commands/chat_commands.py`,
  `commands/_heavy_lane.py`, WAL pragmas on both chat graphs, `commands/__init__.py` registration.
  **Action for the first Track-A session: verify + commit A1 as its own commit before A2.**

## Context — why
Local models on the DGX Spark (ds4 / DeepSeek-V4-Flash, Ollama) are slow (ds4 cold start up to ~180 s,
single-stream). Today notebook chat is one blocking HTTP call and source chat is fake-SSE blocking; the
in-flight state is notebook-scoped, so leaving the page feels like losing the work. **Goal:** route slow
local-model chat through the existing `surreal-commands` worker as tracked **background jobs**, with a
global bottom-corner **tray** aggregating ALL local-model work (chat + podcasts + source/embedding +
transformation), a completion **notification**, and the originating chat showing the answer when ready.
Both notebook and source chat in v1. Full rationale + risks: [design.md](design.md).

## Decisions log (shared)
| # | Question | Decision |
|--:|----------|----------|
| 1 | Durability | **Server-side job queue** — runs on the `surreal-commands` worker; survives refresh/tab-close. |
| 2 | Tray scope | **Unified** — chat + podcasts + source/embedding + transformations in one tray. |
| 3 | Chat surfaces v1 | **Notebook AND source chat** both backgrounded. |

### Decision Register (shared)
> Severity & gating per `~/.claude/skills/severity-model.md`. Gate: S3+ surfaced to the user.
| ID | Decision | Severity (why) | Status | Chosen / default |
|----|----------|----------------|--------|------------------|
| P-durability | Run chat in the worker; worker is the **sole writer** of the LangGraph SQLite checkpoint, API reads only (WAL + busy_timeout). | S4 (architecture; cross-process persistence) | resolved | server-side queue (user-chosen) |
| P-heavy-lane | Serialize heavy/local chat via a process-wide `asyncio.Lock`, gated on resolved provider (ollama/openai_compatible/claude_agent); cloud chats stay parallel. | S3 (correctness vs ds4 single-stream) | resolved | conditional lock |
| P-no-stream | Drop pseudo-streaming/partial_text — the graph returns the full message in one shot, so a mid-flight write is a no-op; UI shows a status-driven "generating" placeholder. | S2 (UX fidelity; reversible) | resolved | status-only placeholder |
| P-status-surface | Implement the existing `list_command_jobs` stub + `GET /commands/jobs?status_filter=active`; no parallel endpoint. Progress (if ever) rides inside `result`. | S2 | resolved | reuse existing route |
| P-tracks | A‖C from start; B joins once A4/A5 land; D last. Shared files: layout.tsx→B, ChatPanel.tsx→C, jobs-store→A. | S3 (merge-safety across concurrent chats) | resolved | 4 tracks |

## Conventions / translation notes (shared)
- **Backend services** are systemd `--user` units: `on-api`, `on-worker`, `on-frontend`. Restart the unit
  to apply code changes (`systemctl --user restart on-worker`); logs via `journalctl --user -u on-worker -f`.
  Do NOT launch services manually.
- **One chunk = one commit** on `feature/multipanelchat` (or the track's worktree branch).
- **surreal-commands**: a command's own id is `input_data.execution_context.command_id`; the worker flips
  status `new→running→completed/failed` itself; raising in the command marks it `failed` with the message.
- **Frontend**: path alias `@/…`; TanStack Query cache keys in `frontend/src/lib/api/query-client.ts`
  (`QUERY_KEYS.notebookChatSession(sessionId)`, `QUERY_KEYS.sourceChatSession(sourceId, sessionId)` —
  both survive navigation). Toasts via `sonner`/`useToast`. Zustand persist pattern: see `auth-store.ts`.
- **i18n**: every new UI string needs a `jobs.*` key in all 14 locale dirs under
  `frontend/src/lib/locales/*/index.ts` (English fallback acceptable for non-en in v1).

## Reference index (shared)
- **Reuse**: podcast job pattern (`commands/podcast_commands.py`, `api/podcast_service.py`), podcast
  polling hook `usePodcastEpisodes` (`frontend/src/lib/hooks/use-podcasts.ts`, dynamic `refetchInterval`),
  status badge map in `frontend/src/components/podcasts/EpisodeCard.tsx`, `patchSessionMessages` in
  `useNotebookChat.ts`, the async→sync bridge in `graphs/chat.py:call_model_with_messages`.
### Post-exploration refinements (confirmed APIs)
- `CommandService.submit_command_job(app, name, args)` → job_id str (`api/command_service.py`).
- `GET /commands/jobs?status_filter=&command_filter=&limit=` already routed (`api/routers/commands.py`);
  `list_command_jobs` is a **stub returning []** — implement it.
- `CommandJobStatusResponse` already has a `progress` field (unused — surreal-commands' native progress is null).
- Chat graph invoke is **sync/blocking** → call via `asyncio.to_thread` in the worker (done in A1).
- `is_heavy_model` / `heavy_lane` live in `commands/_heavy_lane.py` (A1).

## Completion & archival
The track that marks the **last** chunk ☑ (sees every track complete in the Global status table) appends a
final Changelog line and moves the **whole feature directory** to `.claude/plans/archived/background-jobs/`
(`mkdir -p .claude/plans/archived && mv .claude/plans/background-jobs .claude/plans/archived/`), then tells
the user the plan is complete and archived.