# Per-Chat Context for Side Chats — Track B: Frontend

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared
> decisions, conventions, the `context_config` shape, file ownership — then execute this track's chunks
> here, one per session. You should never need to open `a-backend.md`.
> **Location:** `.claude/plans/per-chat-context/b-frontend.md` → archived with the directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps (code):** none — B's code can be written + typecheck-verified without Track A running
(the `context_config` contract is fixed in the coordinator). **For manual end-to-end verification**
(real round-trip), Track A (Backend) must be ☑ — check the coordinator's Global status table.
**Concurrent with:** Track A — fully file-disjoint, run both at once in separate chats.
**Intra-track order:** B1 → B2 → B3 (each depends on the prior).
**State at handoff (2026-06-23):** planning complete; no code written.
**Paste-able resume prompt (run in a fresh chat):**
> Continue Per-Chat Context Track B (Frontend). Read `.claude/plans/per-chat-context/coordinator.md`
> then `.claude/plans/per-chat-context/b-frontend.md` in full. Implement the next unstarted chunk (one
> only, in order B1→B2→B3), verify it (`cd frontend && npx tsc --noEmit`), then update BOTH this
> file's Status table AND the coordinator's Global status table + Changelog, and tell me when it's safe
> to clear context. If that was the last chunk of the last track, archive the feature directory per the
> coordinator's Completion section.

## This track's file ownership
Files this track creates/modifies (disjoint from Track A):
- `frontend/src/lib/types/api.ts`
- `frontend/src/lib/api/chat.ts`
- `frontend/src/lib/hooks/useNotebookChat.ts`
- `frontend/src/components/notebooks/PoppedChatPanel.tsx`
- `frontend/src/components/notebooks/DeepDiveWorkspace.tsx`
- `frontend/src/lib/locales/*` (all locales)
- (possibly a new small popover component under `frontend/src/components/notebooks/`)
Shared files I must NOT touch: none (Track A is backend-only).
> Note: `frontend/src/lib/utils/source-context.ts` is **read/reuse only** — no `insightsSnapshot`
> helper is needed (quote-only default). Reuse the existing `applyBulkSourceContext` etc.

## Per-chunk workflow
read referenced files → implement → verify (`cd frontend && npx tsc --noEmit`) → mark ☑ in this file
AND the coordinator → note new Open Questions → announce "✅ Chunk B<n> complete — safe to clear
context" → stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| B1 | Frontend types + chat-api passthrough | ☐ todo | | |
| B2 | `useNotebookChat`: per-session resolution + quote-only seed + setter | ☐ todo | | needs B1 |
| B3 | Side-chat Context popover UI + i18n | ☐ todo | | needs B2 |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet)_

## Chunks (verbatim)

### Chunk B1 — Frontend types + chat-api passthrough
- **Goal:** Carry `context_config` on the session types and through the create/update API calls so the
  cache (and `sendMessageTo`) can read each session's selection.
- **Read first:** `frontend/src/lib/types/api.ts` (session types: `BaseChatSession`,
  `NotebookChatSession`, `NotebookChatSessionWithMessages`, and the create/update request types);
  `frontend/src/lib/api/chat.ts` (`createSession`/`updateSession`); `@/lib/types/notebook-context`
  (the `ContextSelections` / `ContextMode` types).
- **Spec / exact values:** `context_config?: ContextSelections | null` — shape per coordinator
  Conventions. `null` = inherit.
- **Reuse:** import the existing `ContextSelections` type (don't redefine the shape).
- **Steps:**
  1. Add `context_config?: ContextSelections | null` to the session response types and the
     create/update request payload types in `api.ts`.
  2. Ensure `chatApi.createSession` / `updateSession` include `context_config` in the request body
     (typically automatic once the request type carries it — verify the body isn't field-picked).
- **Verify:** `cd frontend && npx tsc --noEmit` clean (re: these files).

### Chunk B2 — `useNotebookChat`: per-session resolution + quote-only seed + setter
- **Goal:** Each session sends its **own** context if it has one, else the global drawer selection;
  new side chats are seeded **quote-only** (empty `{sources:{},notes:{}}`); add a silent setter.
- **Read first:** `frontend/src/lib/hooks/useNotebookChat.ts` — `buildContext` (233-273),
  `sendMessageTo` (292-372, esp. the cached-session read at 322-324 and the `buildContext()` call at
  ~339), `createSubChat` (424-447), `createSidePanel` (454-471), `setSessionModelOverride` (523-536),
  the token-count effect (576-602), and the hook's return object (604-641).
- **Spec / exact values:**
  - Resolution rule: if the cached session's `context_config` is a non-null object →
    `buildContextFor(context_config)`; else → global `buildContext()`. (`null`/absent = inherit.)
  - New-side-chat seed: `context_config: { sources: {}, notes: {} }` (explicit empty = quote-only) on
    **both** `createSubChat` and `createSidePanel` create payloads.
- **Reuse:** existing `chatApi.updateSession` + `queryClient.invalidateQueries` pattern from
  `setSessionModelOverride`.
- **Steps:**
  1. Refactor `buildContext` into a pure `buildContextFor(selections: ContextSelections)` doing the
     existing source/note → `'insights'|'full content'|'not in'` mapping + POST; keep
     `const buildContext = useCallback(() => buildContextFor(contextSelections), [...])` for the dock
     and the token-count effect (576-602) — those stay on the global selection.
  2. In `sendMessageTo`, after the existing cached-session read (322-324), read
     `cachedSession?.context_config`; choose `buildContextFor(sessionConfig)` when it's a non-null
     object, else `buildContext()`. Use that for the message's context.
  3. In `createSubChat` (424-447) and `createSidePanel` (454-471), add
     `context_config: { sources: {}, notes: {} }` to the `chatApi.createSession({...})` payload.
  4. Add `setSessionContextConfig = useCallback(async (sessionId, config: ContextSelections | null) => {…})`
     mirroring `setSessionModelOverride` (direct `chatApi.updateSession(sessionId, { context_config: config })`
     + invalidate `notebookChatSessions(notebookId)` and `notebookChatSession(sessionId)`); export it
     in the hook's return object.
- **Verify:** `cd frontend && npx tsc --noEmit` clean. Reason through: dock send still uses global;
  a side chat with empty config sends no sources; a side chat with `null` config inherits global.

### Chunk B3 — Side-chat Context popover UI + i18n
- **Goal:** A compact per-side-chat Context editor so the user can opt sources/notes in/out (and pick
  insights vs full) for that chat, plus "Reset to notebook default" (→ `null`).
- **Read first:** `frontend/src/components/notebooks/PoppedChatPanel.tsx` (header row 78-106; it has
  `notebookId`, `session`, `chat`); `frontend/src/components/notebooks/DeepDiveWorkspace.tsx`
  (`useNotebookWorkspaceStrict()` exposes `sources`/`notes`; `PoppedChatPanel` is rendered ~219-229);
  `frontend/src/components/common/ContextToggle.tsx`; `frontend/src/lib/utils/source-context.ts`
  (`applyBulkSourceContext`, `applyBulkNoteContext`, `bulkModeForSource`);
  `frontend/src/components/ui/popover.tsx` (or the existing popover primitive); `frontend/src/lib/locales/en-US/`.
- **Spec / exact values:**
  - Trigger: a small icon button in `PoppedChatPanel`'s header row with a count badge of included
    sources/notes (mode ≠ `off`). For the quote-only default the badge reads 0.
  - Popover body: title "Context for this chat"; a row per notebook source/note using `ContextToggle`
    (off→insights→full, gated by `hasInsights`); bulk actions (insights-only / exclude-all / include)
    reusing `applyBulkSourceContext`/`applyBulkNoteContext`; a "Reset to notebook default" affordance.
  - Reading current state: the side chat's `session.context_config` (object) → render those modes; if
    `null` (inheriting) show the global selection as the displayed baseline and label it "inheriting
    notebook default".
  - Writing: each change calls `chat.setSessionContextConfig(session.id, nextConfig)`; "Reset" calls
    `chat.setSessionContextConfig(session.id, null)`.
- **Reuse:** `ContextToggle` + the bulk helpers verbatim (same controls as the Utility Drawer);
  existing popover UI primitive. Do not rebuild toggle logic.
- **Steps:**
  1. Thread `sources`/`notes` from `DeepDiveWorkspace` (via `useNotebookWorkspaceStrict`) into
     `PoppedChatPanel` props (or read the workspace context directly in `PoppedChatPanel`).
  2. Build the Context popover (inline in `PoppedChatPanel` or a small new
     `SideChatContextPopover.tsx`), wired as above.
  3. Add i18n keys (e.g. `chat.contextForThisChat`, `chat.resetToNotebookDefault`,
     `chat.inheritingNotebookDefault`, `chat.contextIncludedCount`) to **all** locales under
     `frontend/src/lib/locales/*` (en-US first as reference).
- **Verify:** `cd frontend && npx tsc --noEmit` clean; lint clean. **End-to-end (needs Track A ☑):**
  set a source to `full` in the drawer; spawn a side chat from a highlight → its references resolve to
  the quote only (no full text); open the popover, opt that source in at `insights`, send → only
  insights cited; "Reset to notebook default" → side chat follows the drawer again; reload → the side
  chat keeps its custom selection. Confirm the main dock chat still uses the global selection.

## Open Questions (this track)
- **Q-quote-first-turn** — Optional/deferred: also prepend the `quote` to the *first* user message so
  it's grouped with the first prompt in history. Default: **skip** — the system-prompt seed passage
  already gives the model the quote on every turn; only revisit if the model loses focus on later turns.
- **Q-popover-home** — Header icon-button vs composer-toolbar (next to `ChatModelPicker`). Default:
  **header row**, alongside the existing dock-back/promote/delete/hide controls.
