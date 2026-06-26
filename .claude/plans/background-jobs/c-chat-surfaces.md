# Background Jobs — Track C: Chat Surfaces (notebook + source)

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first, then execute this
> track's chunks here, one per session.
> **Location:** `.claude/plans/background-jobs/c-chat-surfaces.md`.

## SESSION HANDOFF — resume here
**Track deps:** **C1 is dependency-free — start any time** (even while Track A runs). **C2 requires A2 + A5
☑; C3 requires A3 + A5 ☑** — check the coordinator before those chunks.
**Concurrent with:** Track A and Track B (disjoint files — C owns chat hooks/components only).
**This chat owns ONLY:** `frontend/src/components/source/chat/ChatPanel.tsx`,
`frontend/src/components/notebooks/chat/{ChatDock,PoppedChatPanel}.tsx`,
`frontend/src/lib/hooks/{useNotebookChat,useSourceChat}.ts`,
`frontend/src/lib/api/source-chat.ts`, and the chat message **type** (e.g. `NotebookChatMessage`/source msg type).
Never edit `jobs-store.ts` / `commands.ts` / `chat.ts` / `query-client.ts` (Track A owns — import only) or
`layout.tsx` / `components/jobs/*` (Track B).
**State at handoff (2026-06-25):** not started. C1 can begin immediately.
**Paste-able resume prompt — re-runnable:**
> Continue Background-Jobs Track C. Read `.claude/plans/background-jobs/coordinator.md` then
> `.claude/plans/background-jobs/c-chat-surfaces.md` in full. Derive the next unstarted chunk from this
> track's Status table + `git log`. C1 is dep-free; before C2 confirm Track A chunks 2 & 5 are ☑, before C3
> confirm A3 & A5 ☑ (stop if not). Implement exactly ONE chunk (reuse `patchSessionMessages` + the existing
> optimistic-message pattern; smallest faithful diff; every job keyed strictly by `sessionId`). Touch ONLY
> Track C's files. Verify (`npx tsc --noEmit` + the manual flow); don't commit red. Commit just that chunk.
> Update BOTH this track file's Status table AND the coordinator's Global status table + Changelog. Announce
> "✅ Chunk C.n complete — safe to clear context. Next: <derived>" and stop. If this completes EVERY track,
> archive per the coordinator.

## This track's file ownership
Modifies: `components/source/chat/ChatPanel.tsx`, `components/notebooks/chat/ChatDock.tsx`,
`components/notebooks/chat/PoppedChatPanel.tsx`, `lib/hooks/useNotebookChat.ts`, `lib/hooks/useSourceChat.ts`,
`lib/api/source-chat.ts`, the chat message type def.
Imports but never edits: `jobs-store.ts` (Track A), `chat.ts` (Track A, 202 return), `query-client.ts`.

## Per-chunk workflow
read referenced files → implement → verify → commit → mark ☑ here AND in coordinator → announce
"✅ Chunk C.n complete — safe to clear context" → stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| 1 | shared pending/error chat bubble + message types | ☐ todo | | dep-free |
| 2 | notebook send/receive refactor | ☐ todo | | dep A2, A5, C1 |
| 3 | source-chat → cache-backed + job-tracked | ☐ todo | | dep A3, A5, C1 |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet)_

## Chunks (verbatim)

### Chunk 1 — shared pending/error chat bubble + message types  (dep-free)
- **Goal:** render an "assistant is generating" skeleton and an error state for a chat message, shared by
  notebook + source chat. No store/endpoint dependency — pure rendering + type.
- **Read first:** `frontend/src/components/source/chat/ChatPanel.tsx` (props interface ~32–50; delegates
  message list to `MessageList.tsx`; `isStreaming` state ~34/151); the `SourceChatMessage` type it consumes.
- **Steps:**
  1. Add optional `pending?: boolean` and `error?: boolean` (or `status?: 'pending'|'error'`) to the chat
     message type used by `ChatPanel` (and `NotebookChatMessage`).
  2. In the `ChatPanel` message map: when a message is `pending`, render a skeleton/typing bubble (reuse the
     existing streaming-indicator spinner styling); when `error`, render an error bubble with a subtle retry affordance.
  3. Keep it presentational — no data fetching here. Both notebook and source chat will set these flags.
- **Verify:** `npx tsc --noEmit`; a story/manual render with a `pending` message shows the skeleton; normal
  messages unaffected. (No backend needed.)

### Chunk 2 — notebook send/receive refactor  (dep A2 + A5 + C1)
- **Goal:** decouple send from receive — submit a job, show a placeholder, let Track B's poller deliver the answer.
- **Read first:** `frontend/src/lib/hooks/useNotebookChat.ts` (`getIsSending` ~123, `patchSessionMessages` ~136, `sendMessageTo` ~152),
  `frontend/src/lib/stores/jobs-store.ts` (A5), `frontend/src/lib/api/chat.ts` (A2, now returns `{job_id}`),
  `components/notebooks/chat/ChatDock.tsx`, `components/notebooks/chat/PoppedChatPanel.tsx`.
- **Steps:**
  1. In `sendMessageTo`: keep the optimistic user message + auto-create-session. Replace the blocking call
     with `const { job_id } = await chatApi.sendMessage({...})`.
  2. `useJobsStore.getState().register({ jobId: job_id, kind:'notebook_chat', sessionId, notebookId, label: message.slice(0,60), status:'new', startedAt: new Date().toISOString() })`.
  3. Insert an assistant placeholder into the cache: `patchSessionMessages(sessionId, prev => [...prev, { id: 'pending-'+job_id, type:'ai', content:'', pending:true, timestamp: new Date().toISOString() }])`.
  4. Return `{ ok:true }` on successful **submit**; on submit failure keep the existing `{ ok:false }`
     draft-restore path (strip the optimistic user message). The poller (Track B) handles completion
     (invalidate → placeholder replaced by real message) and failure (toast).
  5. Replace `getIsSending(sessionId)` to derive from `useJobsStore`'s `hasActiveForSession(sessionId)` (keep
     the brief local flag only for the submit round-trip). Every job strictly keyed by `sessionId` → no
     cross-panel bleed in the multi-panel dock.
  6. `components/notebooks/chat/ChatDock.tsx` / `components/notebooks/chat/PoppedChatPanel.tsx`: read the store-derived sending state; otherwise unchanged
     (they already pass `getMessages(sessionId)`/`getIsSending(sessionId)`).
- **Reuse:** `patchSessionMessages`, the existing optimistic-message + `{ ok:false }` contract.
- **Verify:** `npx tsc --noEmit`; restart `on-frontend`; send a notebook chat against a local model →
  placeholder skeleton appears, network shows `202 {job_id}`; navigate away and back → answer rendered
  (poller invalidated the session). Two popped panels send simultaneously → each answer lands in the
  correct panel.

### Chunk 3 — source-chat → cache-backed + job-tracked  (dep A3 + A5 + C1)
- **Goal:** move source chat off component `useState`+SSE onto the query cache + job model, so results
  survive navigation and show in the tray.
- **Read first:** `frontend/src/lib/hooks/useSourceChat.ts` (whole — `useState` messages ~21, SSE parse
  ~140–181, send fn ~102), `frontend/src/lib/api/source-chat.ts`, `frontend/src/lib/api/query-client.ts`
  (`QUERY_KEYS.sourceChatSession(sourceId, sessionId)`), `useNotebookChat.ts` (mirror its pattern).
- **Steps:**
  1. Move messages from component `useState` to the TanStack cache keyed `QUERY_KEYS.sourceChatSession(sourceId, sessionId)` with a `patchSourceSessionMessages` helper mirroring `patchSessionMessages`.
  2. `source-chat.ts`: change `sendMessage` from the SSE `fetch().then(r=>r.body)` to a normal `apiClient.post` returning `{ job_id, session_id }` (matches A3).
  3. In the hook's send: optimistic user message → `register({ kind:'source_chat', sessionId, targetId: sourceId, label })` → insert `pending-'+job_id` assistant placeholder. Delete the manual SSE reader.
  4. The poller (Track B) invalidates `sourceChatSession` on completion → placeholder replaced.
  5. Update the source page / `ChatPanel` props to read the cache-backed messages + store-derived sending.
- **Reuse:** the notebook-chat pattern from C2; existing `sourceChatSession` query key.
- **Verify:** `npx tsc --noEmit`; restart `on-frontend`; send a source chat → placeholder; navigate away
  and back → answer persists (previously lost); job shows in the tray.

## Open Questions (this track)
- **Q-source-key** — confirm `QUERY_KEYS.sourceChatSession(sourceId, sessionId)` exists/!shape in
  `query-client.ts`; if the current `useSourceChat` uses ad-hoc literals, standardize on `QUERY_KEYS` in C3
  (do not edit `query-client.ts` if the key already exists; if a key must be ADDED, that's a Track-A
  shared-file change — coordinate, don't edit it from Track C).