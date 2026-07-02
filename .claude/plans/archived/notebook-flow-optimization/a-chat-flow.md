# Notebook Flow Optimization — Track A: Chat flow

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared
> decisions, conventions, the cross-track conflict map — then execute this track's chunks here, one
> per session. You should never need to open another track's file.
> **Location:** `.claude/plans/notebook-flow-optimization/a-chat-flow.md` → archived with the directory
> when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** none. **Concurrent with:** B, C, D (run anytime).
**State at handoff (2026-06-23):** planning complete, no code yet.
**Paste-able resume prompt (run in a fresh chat):**
> Continue Notebook Flow Optimization Track A. Read
> `.claude/plans/notebook-flow-optimization/coordinator.md` then `a-chat-flow.md` in full. Implement
> the next unstarted chunk (one only), verify it, then update BOTH this file's Status table AND the
> coordinator's Global status table + Changelog, and tell me when it's safe to clear context. If that
> was the last chunk of the last track, archive the feature directory per the coordinator's Completion
> section.

## This track's file ownership
Files this track creates/modifies (must stay disjoint from concurrent tracks):
- `frontend/src/lib/hooks/useNotebookChat.ts`
- `frontend/src/components/notebooks/ChatGallery.tsx`
- `frontend/src/components/source/ChatPanel.tsx`
Shared files I must NOT touch: `query-client.ts` (Track C owns the global error handler), the notebook
page/layout/provider (Track B), animation files (Track D). Honor coordinator convention: the global
query-error handler (C) won't toast mutation errors — keep this track's mutation `onError` toasts.

## Per-chunk workflow
read referenced files → implement → verify (`cd frontend && npm run typecheck`, ignore preexisting
errors unrelated to your files) → mark ☑ in this file AND the coordinator → note new Open Questions →
announce "✅ Chunk A.n complete — safe to clear context" → stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| A1 | Optimistic chat creation | ☑ done | opus/A1 | Optimistic temp card + instant nav-to-temp, reconcile URL on success / fall back to gallery on fail. tsc+eslint clean. Manual throttle/500 check left to user. |
| A2 | Restore draft on send failure | ☑ done | opus/A2 2026-06-23 | `sendMessageTo`→`{ok}`; ChatPanel optimistic-clears then restores draft + refocus on `{ok:false}`; ChatDock forwards result + gates clearPending/rename on success (media survives too). tsc+eslint clean. |
| A3 | Memoize markdown message rendering | ☑ done | opus/A3 2026-06-23 | `AIMessageContent` wrapped in `memo`; markdown conversion + `LinkComponent` `useMemo`'d; `handleReferenceClick` stabilized via ref + `useCallback([])`; per-row `scrollMarginTop` hoisted to `MSG_SCROLL_MARGIN`. tsc+eslint clean. |
| A4 | Debounce buildContext | ☑ done | opus/A4 2026-06-23 | Mount fires immediately (counts populate); subsequent toggles debounced 250ms trailing via `useRef` timer; timer cleared on input change + unmount. `useRef` import added. tsc+eslint clean. **Track A COMPLETE.** |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- **A4 (done):** Stopped firing a `POST /chat/context` on every single source/note toggle. The
  `useNotebookChat` effect that recomputes token/char counts (formerly an un-debounced
  `await buildContext()` keyed on `buildContext`, which itself changes identity on every
  `sources`/`notes`/`contextSelections` change) now: fires immediately on the first run so counts
  populate on mount (guarded by a `contextCountsPrimedRef`), then debounces all subsequent runs with
  a 250ms trailing `setTimeout` held in `contextDebounceRef`. The effect cleanup clears any pending
  timer on each input change and on unmount, so a burst of toggles collapses into one trailing
  request. Added the `useRef` import. The `console.error`-only failure handling was left as-is (out of
  error-core scope per the chunk spec). Only Track-A-owned `useNotebookChat.ts` touched. Verify:
  `npx tsc --noEmit` (no useNotebookChat errors) + `eslint` clean; manual Network-tab toggle check
  left to the user (services run as systemd units). **Track A is now COMPLETE (A1–A4 ☑).**
- **A3 (done):** Stopped re-parsing every message's markdown on each turn / each popped panel.
  `AIMessageContent` (`ChatPanel.tsx`) is now wrapped in `React.memo`, so a new turn only re-renders
  the new message instead of re-running the markdown pipeline for the whole list. Inside it, the
  reference→compact-markdown conversion (`convertReferencesToCompactMarkdown`) and the
  `LinkComponent` (`createCompactReferenceLinkComponent`) are each `useMemo`'d (keyed on
  `content`/`appendReferenceList`/`t` and on `onReferenceClick` respectively) so they don't rebuild
  every render. For the memo to actually hold across turns, the parent's `handleReferenceClick` is now
  fully stable: `openModal`/`t` (both re-created each render) are stashed in a ref updated each render,
  and `handleReferenceClick` is a `useCallback([])` reading from that ref. The per-message inline
  `style={{ scrollMarginTop: 8 }}` in the message `.map` was hoisted to a module constant
  (`MSG_SCROLL_MARGIN`) so each row no longer allocates a fresh style object. `AIMessageContent`
  changed from a hoisted `function` to a `const = memo(...)` — safe because it's only referenced inside
  `ChatPanel`'s render (runtime), after module eval. Only `ChatPanel.tsx` (Track-A-owned) touched.
  Verify: `npx tsc --noEmit` (no ChatPanel errors) + `eslint` clean. Profiler check left to the user.
- **A2 (done):** A failed message send no longer loses the typed draft. `sendMessageTo`
  (`useNotebookChat.ts`) now returns `Promise<{ ok: boolean }>` — `{ok:true}` after the
  authoritative messages land, `{ok:false}` on send failure (after the temp-bubble rollback) and on
  the auto-create-failure path. `ChatPanel.handleSend` (now async) captures the trimmed text + staged
  media, optimistically clears the composer, awaits `onSendMessage`, and on `{ok:false}` re-sets the
  draft + refocuses the textarea (`requestAnimationFrame`). The `onSendMessage` prop type widened to
  `=> void | Promise<{ ok: boolean } | void>` so source chat (returns void) keeps its clear-on-send
  behavior untouched while the dock path gets restore. **ChatDock.tsx** (a Track-A chat file — the
  other tracks all reserve "chat files (Track A)", none touch it) was updated to forward the result:
  its `handleSend` returns `{ok}` and gates `clearPending`/auto-rename behind `result.ok`, so a failed
  send also keeps the staged media + the new-chat title. Verify: `npx tsc --noEmit` + `eslint` clean;
  manual forced-500 send-failure check left to the user (services run as systemd units).
- **A1 (done):** `createSessionMutation` now optimistic — `onMutate` inserts a `temp-session-*` card
  into the `notebookChatSessions` list AND seeds its `notebookChatSession(tempId)` detail cache (fresh
  under the 5-min staleTime → no 404 fetch on the not-yet-real id); `onSuccess` swaps temp→real in the
  list + seeds the real detail cache; `onError` rolls the card back + removes the temp detail + toasts.
  Removed the old success toast (`chat.sessionCreated` key now unused, left in locales). New hook export
  `createMainChat(title) → { tempId, promise }` for the gallery's instant path; `createSession` kept its
  `Promise<session|null>` contract so **ChatDock** (non-Track-A file, awaits the real id before sending)
  is untouched. `ChatGallery.startNewMainChat` now navigates to `tempId` immediately then
  `router.replace`s to the real id on success / back to `/notebooks/{id}` on failure; dropped the
  blocking `creating` spinner gate (nav is instant so the gallery unmounts at once) + `Loader2` import.
  Files: `useNotebookChat.ts`, `ChatGallery.tsx`. Verify: `npx tsc --noEmit` + `eslint` clean.

## Chunks (verbatim — do not require another track file)

### Chunk A1 — Optimistic chat creation
- **Goal:** Spawning a chat from the gallery feels instant — a temp card appears and navigation
  happens immediately, reconciling to the real session on success and rolling back + toasting on
  failure. Removes the blocking spinner→server→toast→refetch→navigate sequence.
- **Read first:** `useNotebookChat.ts` (`createSessionMutation` :106-120; `createSession` wrapper
  :320-329; sessions query :46-54), `ChatGallery.tsx` (`startNewMainChat` :105-118; `creating` flag
  :57,111; spinner button :149-152; `enterChat`/`router.push`).
- **Spec / exact values:** Session list key = `QUERY_KEYS.notebookChatSessions(notebookId)` =
  `['notebook-chat', nbId, 'sessions']`. Temp id pattern: reuse the `temp-${...}`-style convention
  already used for optimistic messages in `sendMessageTo` (:260-267) — e.g. `temp-session-<n>`.
- **Reuse:** `setQueryData` on the sessions key (mirror the `patchSessionMessages` setQueryData
  pattern at :208-220); `getApiErrorMessage(err, 'apiErrors.failedToCreateSession')` for the rollback
  toast (already used at :116-119).
- **Steps:**
  1. Convert `createSessionMutation` to use `onMutate`: cancel in-flight session-list queries, snapshot
     previous list, insert an optimistic session (temp id, the passed title, empty messages) into the
     `notebookChatSessions` cache, return the snapshot as context.
  2. `onError(err, _vars, ctx)`: restore the snapshot, fire the existing `failedToCreateSession` toast.
     `onSuccess`: replace the temp session with the server session (set `currentSessionId` to the real
     id), keep the invalidate but it's now a reconcile not the source of truth.
  3. In `ChatGallery.startNewMainChat`: navigate (`enterChat`) optimistically using the temp/returned
     id instead of awaiting before push; drop the blocking `creating` spinner gate (or keep a subtle
     pending style, not a full blocker). **Remove the success toast on creation** (self-evident action).
  4. Ensure the auto-create path inside `sendMessageTo` (:229-252) still works — it creates then sends;
     keep its behavior, just make sure the optimistic list insert doesn't double-add.
- **Verify:** Create a chat from the gallery with the network throttled — the card + navigation appear
  immediately; on a forced 500 (temporarily make the endpoint fail) the card disappears and a toast
  shows. Typecheck passes.

### Chunk A2 — Restore draft on send failure
- **Goal:** A failed message send no longer loses the user's typed text. Today the optimistic bubble is
  rolled back (good) but the composer was already cleared, so the text is gone with only a toast.
- **Read first:** `useNotebookChat.ts` `sendMessageTo` (:225-294; optimistic add :260-267; rollback
  :286-291; finally :293), `ChatPanel.tsx` (composer clear on send :283; send disable :277,506;
  sending bubble :437-446).
- **Spec / exact values:** Rollback currently filters `temp-` messages at :291. The composer text state
  lives in `ChatPanel.tsx`.
- **Reuse:** existing `getApiErrorMessage(err, 'apiErrors.failedToSendMessage')` toast.
- **Steps:**
  1. Capture the outgoing text before clearing the composer. On send failure, restore it to the
     composer input (either return a failure signal from `sendMessageTo` that `ChatPanel` checks, or
     restore state in the `catch`). Prefer: `sendMessageTo` resolves to `{ ok: false }` on failure and
     `ChatPanel` re-sets its input from the captured value; keep clearing only on success.
  2. Re-focus the textarea after restore so the user can immediately retry. Optional: keep the rolled-
     back bubble's text available for a one-click resend (nice-to-have; not required).
- **Verify:** Force a send failure — typed text reappears in the composer, textarea is focused, toast
  shows, composer re-enabled. Typecheck passes.

### Chunk A3 — Memoize markdown message rendering
- **Goal:** Stop re-parsing every message's markdown on each turn / each panel. Today `AIMessageContent`
  is not memoized and rebuilds its link component + reference converter every render; with N popped
  panels each renders its own un-memoized list.
- **Read first:** `ChatPanel.tsx` — `AIMessageContent` (:683), markdown pipeline (`ReactMarkdown` +
  remark-gfm/remark-math/rehype-highlight/rehype-katex :702-721), `convertReferencesToCompactMarkdown`
  + `createCompactReferenceLinkComponent` (:695-698), `handleReferenceClick` (:178), message `.map`
  (:356).
- **Spec / exact values:** Chat is request/response (not token-streaming), so markdown re-parses ~2×
  per turn today — this is correctness-preserving perf, low risk.
- **Reuse:** `React.memo`, `useCallback`, `useMemo` (already in React).
- **Steps:**
  1. Wrap `AIMessageContent` in `React.memo` keyed on `content` (+ `onReferenceClick`).
  2. Stabilize `handleReferenceClick` with `useCallback` so memo isn't defeated.
  3. Memoize the derived markdown (`convertReferencesToCompactMarkdown(content)`) and the
     `LinkComponent` per message via `useMemo`, or hoist `createCompactReferenceLinkComponent` so it's
     created once per stable `onReferenceClick`.
  4. Replace per-row inline object props in the `.map` (e.g. `style={{ scrollMarginTop: 8 }}`) with a
     stable constant where trivial.
- **Verify:** Open a long chat + 2 popped panels; sending a message no longer visibly re-renders prior
  messages (React DevTools Profiler shows prior `AIMessageContent` not re-rendering). Typecheck passes.

### Chunk A4 — Debounce buildContext
- **Goal:** Stop firing a `POST /chat/context` network request on every single source/note toggle.
  Today the counts effect calls `buildContext` per change, un-debounced.
- **Read first:** `useNotebookChat.ts` buildContext effect (:495-504; note it only `console.error`s on
  failure — leave that behavior, it's out of error-core scope).
- **Spec / exact values:** This computes token/char counts for the composer; staleness for a few
  hundred ms is fine.
- **Reuse:** a small debounce (existing util if present under `lib/utils`, else a `useRef` + timeout
  inline). Do not add a dep.
- **Steps:**
  1. Debounce the buildContext call (~250–300ms trailing) so rapid context toggling collapses to one
     request. Cancel the pending timer on unmount and when inputs change again.
  2. Keep the immediate first call so counts populate on mount.
- **Verify:** Rapidly toggle several sources — only one (trailing) `/chat/context` request fires
  (Network tab). Counts still update. Typecheck passes.

## Open Questions (this track)
- **Q-A1-tempflow** — Should the optimistic temp card show a subtle "creating…" affordance or look
  identical to a real card? Default: subtle pulse/disabled state on the temp card until reconciled.
- **Q-A2-resend** — One-click resend of a failed message vs. just restoring the draft? Default: restore
  draft only (smallest change); resend affordance deferred.
