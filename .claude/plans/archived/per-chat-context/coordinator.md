> ⚠️ **SUPERSEDED (2026-06-23)** by the merged plan at `.claude/plans/chat-foundation/coordinator.md`,
> which combines this feature with auto-illustrate-chat (shared files + single migration 18, worktree
> orchestrator). Execute from there, not here. The rationale below is folded into the merged coordinator.
> Delete this dir when chat-foundation is archived.

# Per-Chat Context for Side Chats — Coordinator / Index

> **Shared source of truth for a multi-track plan.** This file holds everything common to all tracks.
> Each track is executed from its own file (`<track>.md` in this directory) by its own chat.
> A track chat reads THIS file first, then owns exactly one track file.
> **Location:** `.claude/plans/per-chat-context/coordinator.md` → the whole directory is archived to
> `.claude/plans/archived/per-chat-context/` once every track is ☑.
>
> Supersedes the loose draft at `.claude/plans/shimmering-fluttering-candle.md` (same feature; the
> default was since changed to **quote-only**, which drops the `insightsSnapshot` helper).

## How to run this plan (read first)
1. Pick a track whose deps are ☑ in the Global status table below and whose row is **runnable now**.
2. Open its file (`a-backend.md` or `b-frontend.md`) in a fresh chat; that file is self-contained.
3. Tracks A and B are **file-disjoint** → you may run both at the same time in separate chats.
4. One chunk per session. On each chunk completion, update BOTH the track file's status AND the Global
   status table here, then announce "safe to clear context" and stop.

## Concurrency matrix
| Track | File | Depends on (must be ☑) | Concurrent with | Sequential after | Why |
|-------|------|------------------------|-----------------|------------------|-----|
| A — Backend | `a-backend.md` | — | B | — | backend-only files, disjoint from B |
| B — Frontend | `b-frontend.md` | — (code) ; A for end-to-end verify | A | — | frontend-only files, disjoint from A |
> Read as: `A ‖ B` run together. The contract (field name `context_config`, shape
> `{ sources: {id:mode}, notes: {id:mode} }`) is **fixed below**, so B can be written and
> typecheck-verified without A running. Only B's *manual end-to-end* verification (real round-trip
> through the API) needs Track A ☑.

## Shared-file ownership (conflict map)
None. Track A touches only `open_notebook/**` + `api/routers/chat.py`; Track B touches only
`frontend/**`. No file is shared, so there is no wait order between them.

## Global status table
| Track | Chunk | Title | Status | Owner / session | Notes |
|-------|------:|-------|--------|-----------------|-------|
| A | A1 | Persist `context_config` on chat sessions (migration + model + API) | ☐ todo | | |
| B | B1 | Frontend types + chat-api passthrough | ☐ todo | | |
| B | B2 | `useNotebookChat`: per-session context resolution + quote-only seed + setter | ☐ todo | | depends on B1 |
| B | B3 | Side-chat Context popover UI + i18n | ☐ todo | | depends on B2 |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (cross-track)
- _(none yet)_

## Context — why
Today a notebook has **one global context selection** (which sources/notes are attached to chat, at
depth `off`/`insights`/`full`), set in the Utility Drawer and held in `NotebookWorkspaceProvider`.
There is a single `useNotebookChat` instance shared by the main dock chat AND every side chat: all of
them call `chat.sendMessageTo()` → `buildContext()` → the same `contextSelections`
([useNotebookChat.ts:233-273](../../../frontend/src/lib/hooks/useNotebookChat.ts#L233-L273)). So if a
source is set to `full`, every chat — including a side chat about one highlighted line — ships the full
source. That is the token waste + "side chat references the whole textbook" bug the user reported.

**Goal:** give each **side chat** its own optional context (`context_config`), defaulting to **quote
only** (no sources), so side chats are token-lean by default while the user can opt specific sources in
per chat. The main dock chat and the global drawer are unchanged (they never set `context_config`).
The `quote` seed-passage path already works (`api/routers/chat.py:613` → `prompts/chat/system.jinja`),
so this plan only adds per-session context selection + its editor UI.

**Build-now:** all chunks A1, B1–B3. **Deferred (not in this plan):** grouping the quote into the
first user message (system-prompt seed already covers it — see Open Questions).

## Decisions log (shared)
| # | Question | Decision |
|--:|----------|----------|
| 1 | Where does per-chat context live? | Persisted nullable `context_config` on the `chat_session` record (consistent with `model_override`/`quote`/`tags`). Survives reload. |
| 2 | What do `null` vs object mean? | `null`/absent → **inherit** the global drawer selection (today's behavior). An object `{sources,notes}` → this chat's **own** explicit selection. |
| 3 | Default for a newly-spawned side chat? | **Quote only** — seed an explicit empty `{ sources: {}, notes: {} }`. Everything off; the chat relies on its `quote` seed passage. User adds sources later via the popover. (User-chosen over insights-snapshot / inherit-as-is.) |
| 4 | How does the dock/main chat behave? | Unchanged. It never sets `context_config`, so it keeps using the global drawer selection. |
| 5 | "Reset to notebook default" in the popover | Sets `context_config = null` → the side chat goes back to inheriting the global selection. |
| 6 | Storage type in SurrealDB | `FLEXIBLE TYPE option<object> DEFAULT NONE` (mirrors migration 17's flexible-object pattern; `chat_session` is SCHEMAFULL so the field must be declared). |

### Decision Register (shared)
> Severity & gating per `~/.claude/skills/severity-model.md`. Gate: S3+ surfaced to the user.
| ID | Decision | Severity (why) | Status | Chosen / default |
|----|----------|----------------|--------|------------------|
| P-storage | Persist `context_config` on the session vs frontend-only store | S3 (data-model + migration; all tracks depend) | resolved | Persist on session (Decision 1) |
| P-default | Default context for new side chats | S3 (drives core token-efficiency goal + UX) | resolved | **Quote only** — empty `{}` (Decision 3, user-chosen) |
| P-resolution | Effective context = session's own if non-null else global | S2 (localized to `sendMessageTo`) | auto-decided | Decision 2/4 |
| P-resetsemantics | "Reset to default" clears to `null` (inherit) | S1 | auto-decided | Decision 5 |

### Reconciliation
No external artifact. The approved design draft (`shimmering-fluttering-candle.md`) is folded in here;
the only delta is Decision 3 (quote-only default) which **removes** the planned `insightsSnapshot`
helper — do not add it.

## Conventions / translation notes (shared)
- **Migration numbering:** next is **18**. Up + down files in `open_notebook/database/migrations/`,
  both registered in `open_notebook/database/async_migrate.py` (the up list currently ends at
  `17.surrealql` near line 127-129; the down list mirrors it). 17 is the latest existing migration.
- **`context_config` JSON shape** (single source of truth for both tracks):
  ```jsonc
  // null  → inherit global drawer selection
  // object → explicit per-chat selection (modes: "off" | "insights" | "full")
  { "sources": { "<source:id>": "insights" }, "notes": { "<note:id>": "full" } }
  ```
  This is the **frontend `ContextSelections`** shape (`@/lib/types/notebook-context`). The backend
  stores it verbatim as an opaque object; it does NOT interpret it (only the frontend's
  `buildContextFor` maps modes → the `/chat/context` payload). So no backend mode-mapping is needed.
- **i18n:** every new UI string needs a key in **all** locales under `frontend/src/lib/locales/*`
  (en-US is the reference; the project requires all locales updated).
- **Silent vs toasting updates:** per-session writes use the *silent* pattern (direct
  `chatApi.updateSession` + targeted invalidation, no "Session updated" toast) — mirror
  `setSessionModelOverride` ([useNotebookChat.ts:523-536](../../../frontend/src/lib/hooks/useNotebookChat.ts#L523-L536)).

## Reference index (shared)
- **Per-session resolution anchor:** `sendMessageTo` already reads the cached session for
  `model_override` at [useNotebookChat.ts:322-324](../../../frontend/src/lib/hooks/useNotebookChat.ts#L322-L324)
  — read `context_config` in the same place.
- **Context builder:** `buildContext` [useNotebookChat.ts:233-273](../../../frontend/src/lib/hooks/useNotebookChat.ts#L233-L273)
  (refactor into `buildContextFor(selections)`).
- **Side-chat creation:** `createSubChat` [useNotebookChat.ts:424-447](../../../frontend/src/lib/hooks/useNotebookChat.ts#L424-L447),
  `createSidePanel` [useNotebookChat.ts:454-471](../../../frontend/src/lib/hooks/useNotebookChat.ts#L454-L471).
- **Silent setter to mirror:** `setSessionModelOverride` [useNotebookChat.ts:523-536](../../../frontend/src/lib/hooks/useNotebookChat.ts#L523-L536).
- **Existing context UI primitives to REUSE (don't rebuild):** `ContextToggle`
  (`frontend/src/components/common/ContextToggle.tsx`), bulk helpers `applyBulkSourceContext` /
  `applyBulkNoteContext` / `bulkModeForSource` (`frontend/src/lib/utils/source-context.ts`).
- **Side-chat panel:** `PoppedChatPanel` header row
  [PoppedChatPanel.tsx:78-106](../../../frontend/src/components/notebooks/PoppedChatPanel.tsx#L78-L106);
  it already receives `notebookId` + the `chat` hook.
- **Sources/notes source:** `useNotebookWorkspaceStrict()` in
  `frontend/src/components/notebooks/DeepDiveWorkspace.tsx` exposes `sources`/`notes` to pass down.
- **Backend session model:** `ChatSession` [notebook.py:683-696](../../../open_notebook/domain/notebook.py#L683-L696)
  (`nullable_fields`, fields). Migration 17 pattern: `open_notebook/database/migrations/17.surrealql`.
- **Backend session CRUD + response builders:** `api/routers/chat.py` — schemas
  `CreateSessionRequest`/`UpdateSessionRequest`/`ChatSessionResponse` (lines 33-143);
  `get_sessions` (337-349), `create_session` (372-396), `get_session` (457-469),
  `update_session` (491-528+).

### Post-exploration refinements (confirmed APIs)
- `ChatSession.nullable_fields` is a `ClassVar[set[str]]` currently
  `{"model_override","parent_session_id","quote"}` — add `"context_config"`.
- `update_session` applies fields via `request.model_dump(exclude_unset=True)` then per-key
  `if "<field>" in update_data:` blocks (lines 491-506) — follow that exact idiom so `null` is
  distinguishable from "not sent" (clearing to null must work for "reset to default").
- `BuildContextRequest`/`buildContext` endpoint is unchanged — it already accepts an arbitrary
  `context_config`; the frontend just sends a different (per-session) one.

## Completion & archival
The track that marks the **last** chunk ☑ (sees every track complete in the Global status table)
appends a final Changelog line and moves the **whole feature directory** to
`.claude/plans/archived/per-chat-context/`
(`mkdir -p .claude/plans/archived && mv .claude/plans/per-chat-context .claude/plans/archived/`), then
tells the user the plan is complete and archived. (Also delete the superseded
`.claude/plans/shimmering-fluttering-candle.md` at that point.)
