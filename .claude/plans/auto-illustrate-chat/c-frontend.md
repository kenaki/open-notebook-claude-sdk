# Auto-Illustrate AI Chat — Track C: Frontend (render + poll + toggle)

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — the data contract
> (`illustration_job_id`, sidecar merge, P-3 diagram-as-mermaid-fence, P-4 invalidate-on-complete) lives
> there. Execute this track's chunks here, one per session.
> **Location:** `.claude/plans/auto-illustrate-chat/c-frontend.md` → archived with the directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** **Track A must be ☑** (check the coordinator Global status table) — C reads A's response
contract (`illustration_job_id`, merged `media`, appended mermaid fence) and the `auto_illustrate` notebook
field/endpoint. (C1, the Mermaid renderer, is technically independent of A — it renders any ` ```mermaid `
fence — but keep the whole track gated on A for a clean integration.)
**Concurrent with:** Track B (backend) — file-disjoint (`frontend/**` only), safe to run at the same time.
**State at handoff (2026-06-23):** planning complete; no code written.
**Paste-able resume prompt (run in a fresh chat):**
> Continue auto-illustrate-chat Track C (Frontend). Read `.claude/plans/auto-illustrate-chat/coordinator.md`
> then `.claude/plans/auto-illustrate-chat/c-frontend.md` in full. Confirm Track A is ☑ in the coordinator.
> Implement the next unstarted chunk (one only), verify it (typecheck/build + click through the app — the
> frontend runs as the `on-frontend` systemd --user unit, do not launch it), then update BOTH this file's
> Status table AND the coordinator's Global status table + Changelog, and tell me when it's safe to clear
> context. If that was the last chunk of the last track, archive per the coordinator's Completion section.

## This track's file ownership
Files this track creates/modifies (disjoint from Track B's Python files):
- `frontend/src/components/source/` — NEW `Mermaid.tsx`; edits to `MarkdownCodeBlock.tsx` and/or
  `ChatPanel.tsx` (the react-markdown `components` map)
- `frontend/src/lib/hooks/useNotebookChat.ts` — job polling + invalidate-on-complete
- `frontend/src/lib/types/api.ts` — `illustration_job_id`, notebook `auto_illustrate`
- `frontend/src/lib/api/` — commands/jobs poll call (if not already present), notebook update typing
- `frontend/src/components/notebooks/` — toggle in the dock-header dropdown (mirror `SideChatDefaultMenu.tsx`)
- `frontend/src/lib/locales/**` — i18n keys for the toggle + any new copy
Shared files I must NOT touch: any Python/backend file (owned by A/B).

## Per-chunk workflow
read referenced files → implement → verify (`cd frontend && npm run build` or typecheck; then click
through the running app) → mark ☑ here AND in the coordinator → announce "safe to clear context" → stop.
One chunk per session. The frontend runs as `on-frontend` (systemd --user) — do NOT launch it; it hot-reloads.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| C1 | Mermaid renderer in react-markdown (strict + DOMPurify + parse-or-fallback) | ☐ todo | | needs A ☑ |
| C2 | Job polling → invalidate session on completion | ☐ todo | | needs A ☑ |
| C3 | Per-notebook auto-illustrate toggle in dock-header dropdown + types | ☐ todo | | needs A ☑ |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet)_

## Chunks (verbatim)

### Chunk C1 — Mermaid renderer in the chat markdown pipeline
- **Goal:** Render fenced ` ```mermaid ` blocks in AI chat messages as diagrams, **safely**: Mermaid
  `securityLevel:'strict'`, `mermaid.parse()` guard, **DOMPurify** on the rendered SVG, and
  **fallback-to-codeblock** on any parse/render failure (never a red error box). This serves both
  model-inline mermaid and the sidecar-appended diagram (P-3).
- **Read first:** `frontend/src/components/source/ChatPanel.tsx:735-784` (`AIMessageContent`, the
  `ReactMarkdown` `components` map — `pre: MarkdownCodeBlock`, `remarkGfm`/`remarkMath`,
  `rehypeHighlight`/`rehypeKatex`); `frontend/src/components/source/MarkdownCodeBlock.tsx` (current code
  block renderer + `extractLanguage`/`extractText` helpers). Coordinator D1 + P-3.
- **Spec / exact values:** Add deps `mermaid` and `dompurify` (`cd frontend && npm install mermaid dompurify`
  — confirm versions against `package.json`). New `Mermaid.tsx`: a client component that takes a `chart:
  string`, runs `mermaid.initialize({ startOnLoad:false, securityLevel:'strict' })` once, `await mermaid.parse(chart)`
  then `mermaid.render(...)`, sanitizes the SVG with DOMPurify, and on any throw renders the raw source via
  the existing code-block UI instead. Detect mermaid in the `components` map: when a fenced block's language
  is `mermaid` (from `extractLanguage(node)`), render `<Mermaid chart={extractText(node)} />`; otherwise
  fall through to `MarkdownCodeBlock`. (Cleanest: wrap the dispatch in `MarkdownCodeBlock` or a small
  `CodeBlock` that branches on language, keeping the single `pre:` mapping.)
- **Reuse:** existing `extractLanguage`/`extractText` from `MarkdownCodeBlock.tsx`; the `chat-codeblock`
  styles for the fallback; the existing `components` map slot — do NOT restructure the markdown pipeline.
- **Steps:**
  1. Install `mermaid` + `dompurify`.
  2. Create `Mermaid.tsx` (strict + parse-guard + DOMPurify + fallback).
  3. Branch the code-block renderer on `language === 'mermaid'`.
  4. Handle theme (light/dark) via mermaid `theme` config to match the app.
- **Verify:** Hardcode an AI message (or paste into chat) containing a ` ```mermaid\ngraph TD; A-->B\n``` `
  block → renders a diagram. Feed an invalid mermaid block → shows the source as a code block, **no red
  error**. Toggle dark mode → diagram readable. `npm run build` clean.

### Chunk C2 — Job polling → invalidate session on completion
- **Goal:** After `/chat/execute` returns an `illustration_job_id`, poll `GET /commands/jobs/{id}` until
  terminal; on `completed`, **invalidate the session query** so the merged illustration hydrates from the
  backend (P-4). On `failed`/timeout, stop quietly (message stays text-only).
- **Read first:** `frontend/src/lib/hooks/useNotebookChat.ts:276-372` (`patchSessionMessages`,
  `sendMessageTo`, where the execute response is handled); `query-client.ts:41-42` (query keys —
  `notebookChatSession(sessionId)`); `RebuildEmbeddings.tsx:45-66` (the 5s poll-until-terminal pattern);
  `frontend/src/lib/api/chat.ts` (`chatApi.sendMessage` response) + any existing commands/jobs API client
  (mirror `embeddingApi.getRebuildStatus`). Coordinator → data contract + P-4.
- **Spec / exact values:** When `sendMessageTo` receives a response with a non-null `illustration_job_id`,
  start a poll (reuse the RebuildEmbeddings interval pattern, ~3–5s, stop on `completed`/`failed`, and a
  safety max-attempts/timeout). On `completed`:
  `queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(sessionId) })`. Ensure polls
  are cleaned up on unmount and don't leak across messages. Add `illustration_job_id?: string` to the
  execute-response type (C-owned types file).
- **Reuse:** `RebuildEmbeddings` poll pattern; `queryClient` + `QUERY_KEYS`; existing commands/jobs API call
  if present, else add a tiny `commandsApi.getJobStatus(id)` to `lib/api/`.
- **Steps:**
  1. Add `illustration_job_id` to the response type.
  2. Add a `commandsApi.getJobStatus` client call if missing.
  3. In `useNotebookChat`, kick off polling after a successful send when a job id is present; invalidate the
     session query on completion; clean up timers.
- **Verify:** With Track B running (or a manually-inserted sidecar row + a fake completed job), send a chat
  message → a beat later the diagram/image **appears on the message without a manual refresh**. Reload the
  page → illustration persists (proves hydrate). No console errors; no runaway intervals (check React
  devtools / network tab stops polling on terminal). `npm run build` clean.

### Chunk C3 — Per-notebook auto-illustrate toggle (dock-header dropdown)
- **Goal:** A per-notebook **auto-illustrate** toggle (default ON), placed in the chat dock-header dropdown
  next to the existing chat setting (P-2), persisting via the notebook update endpoint (A3 added
  `auto_illustrate` passthrough).
- **Read first:** `frontend/src/components/notebooks/SideChatDefaultMenu.tsx` (the dropdown pattern to
  mirror — `DropdownMenu` + label + helper + control); how it's mounted in the dock header (`ChatDock.tsx`);
  `NotebookWorkspaceProvider.tsx` (how `notebook` + updates flow — e.g. the `chat_tag_colors` update path:
  `notebooksApi.update(notebookId, {...})` + `queryClient.setQueryData(QUERY_KEYS.notebook(notebookId), …)`);
  `frontend/src/lib/types/api.ts` (`NotebookResponse`, `UpdateNotebookRequest`); `frontend/src/lib/api/notebooks.ts`.
- **Spec / exact values:** Add `auto_illustrate?: boolean` to `NotebookResponse` and `UpdateNotebookRequest`
  types. In the dock-header dropdown (either extend `SideChatDefaultMenu` or add a sibling control), add a
  checkbox/switch bound to `notebook.auto_illustrate ?? true`; on change call
  `notebooksApi.update(notebookId, { auto_illustrate: next })` and update the notebook cache (mirror the
  tag-colors update). Add i18n keys (e.g. `chat.autoIllustrate`, `chat.autoIllustrateHelper`) to
  `en-US/index.ts` and at least stub them in the other 14 locales.
- **Reuse:** `SideChatDefaultMenu` dropdown structure; the `chat_tag_colors` update+cache pattern in
  `NotebookWorkspaceProvider`; existing Shadcn `Switch`/`Checkbox`; `useTranslation`.
- **Steps:**
  1. Extend the types (`NotebookResponse`, `UpdateNotebookRequest`).
  2. Add the toggle control to the dock-header dropdown, wired to `notebooksApi.update` + cache update.
  3. Add i18n keys across locales.
- **Verify:** Open a notebook → dock-header dropdown shows the auto-illustrate toggle defaulting ON. Turn it
  OFF → `notebooksApi.update` fires, persists across reload (re-open notebook → still OFF). With it OFF, a
  chat message returns `illustration_job_id: null` (no job) — confirm via network tab. `npm run build` clean.

## Open Questions (this track)
- **Q-C-mermaid-ssr** — `mermaid` is browser-only; ensure the `Mermaid` component is client-side
  (`'use client'`) and not imported during SSR. *Default: dynamic import / client component.*
- **Q-C-toggle-host** — extend `SideChatDefaultMenu` vs add a sibling control in the dock header. *Default:
  whichever keeps the dropdown cohesive; mirror the existing structure.*
