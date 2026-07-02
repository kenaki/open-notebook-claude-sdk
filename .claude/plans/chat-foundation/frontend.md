# Chat Foundation — Frontend chunk specs (F1–F6)

> Chunk detail for the frontend lanes. Read `coordinator.md` first (frozen contracts, decisions,
> reference index, i18n key namespaces). Verify each with `cd frontend && npx tsc --noEmit` (and
> `npm run build` for the render chunk); the frontend runs as `on-frontend` (systemd --user, hot-reload)
> — do NOT launch it.

---

## F1 — FE-TYPES: types + chat-api passthrough
- **Owns:** `frontend/src/lib/types/api.ts`, `frontend/src/lib/api/chat.ts`. **Deps:** none.
- **Goal:** Carry the two new fields on the types + session API so the hook/components can read them:
  `context_config` (per-chat), `auto_illustrate` (notebook). *(v2 note: `illustration_job_id` was cut —
  illustration jobs are discovered by the poller, not handed over in a response; coordinator P-5.)*
- **Read first:** `lib/types/api.ts` (session types `BaseChatSession`/`NotebookChatSession`/
  `NotebookChatSessionWithMessages` + create/update request types; `MediaItem` 165-170;
  `NotebookChatMessage` 255-270; `NotebookResponse`/`UpdateNotebookRequest`; the execute-response type);
  `lib/api/chat.ts` (`createSession`/`updateSession`/`sendMessage`); `@/lib/types/notebook-context`
  (`ContextSelections`/`ContextMode`).
- **Spec:**
  - `context_config?: ContextSelections | null` on the session response types + create/update request
    payloads (import the existing `ContextSelections` — do not redefine the shape). `null` = inherit.
  - `auto_illustrate?: boolean` on `NotebookResponse` + `UpdateNotebookRequest`.
  - Ensure `chatApi.createSession`/`updateSession` include `context_config` in the request body (verify the
    body isn't field-picked).
- **Verify:** `cd frontend && npx tsc --noEmit` clean.

## F2 — FE-HOOK: per-session context resolution + quote-only seed + setter
- **Owns:** `frontend/src/lib/hooks/useNotebookChat.ts`. **Deps:** F1.
  > F3 also owns this file (same function `sendMessageTo`) → **F3 runs after F2** even with worktrees.
- **Goal:** Each session sends its **own** context if it has one, else the global drawer selection; new
  side chats seed **quote-only**; add a silent setter.
- **Read first:** `useBuildNotebookContext.ts:26` (`buildContext` callback, now a pure hook; token-count
  effect :58-85); `useNotebookChat.ts` — `patchSessionMessages` :136, `sendMessageTo` :152 (cached-session
  read :175-177, `buildContext()` call :191), return object :235-267;
  `useNotebookChatSessions.ts` — `createSubChat` :164, `createSidePanel` :188, `setSessionModelOverride` :260.
- **Spec:**
  - Refactor `buildContext` (currently in `useBuildNotebookContext.ts:26`) into a pure
    `buildContextFor(selections: ContextSelections)` doing the existing source/note →
    `'insights'|'full content'|'not in'` mapping + POST; keep
    `const buildContext = useCallback(() => buildContextFor(contextSelections), [...])` for the dock + the
    token-count effect (those stay on the global selection in `useBuildNotebookContext.ts`).
  - In `sendMessageTo` (`useNotebookChat.ts:152`), after the cached-session read (:175-177), read
    `cachedSession?.context_config`; use `buildContextFor(sessionConfig)` when it's a non-null object,
    else `buildContext()`.
  - In `createSubChat` (`useNotebookChatSessions.ts:164`) and `createSidePanel` (:188), add
    `context_config: { sources: {}, notes: {} }` to the `chatApi.createSession({...})` payload
    (explicit empty = quote-only).
  - Add `setSessionContextConfig` mirroring `setSessionModelOverride` (`useNotebookChatSessions.ts:260`):
    direct `chatApi.updateSession(sessionId, { context_config: config })`
    + invalidate `notebookChatSessions(notebookId)` and `notebookChatSession(sessionId)`; export it.
- **Verify:** `npx tsc --noEmit` clean. Reason through: dock send still global; side chat with empty config
  sends no sources; side chat with `null` config inherits global.

## F3 — FE-POLLER: `'illustration'` job kind → session invalidate *(revised 2026-07-02 — contract #6 v2)*
- **Owns:** `frontend/src/lib/stores/jobs-store.ts` (the `JobKind` union), 
  `frontend/src/lib/hooks/use-jobs-poller.ts` (`deriveKind` + `handleTermination`). **Deps:** F1.
  > Both files are **background-jobs-owned** (Tracks A5/B1) — F3 may edit them ONLY because the entire
  > background-jobs plan (including bg B3, which also edits `use-jobs-poller.ts` for toasts) lands before
  > chat-foundation starts (meta-coordinator lane rule). Confirm bg is archived before running this chunk.
  > `useNotebookChat.ts` is NOT touched (v1 design) — there is no job id in any response to register;
  > the poller discovers illustration jobs from the active list on its own.
- **Goal:** The poller recognizes `illustrate_message` jobs, tracks them in the store/tray, and on
  `completed` **invalidates the session query** so the merged illustration hydrates from the backend
  (P-4). Silent on both completion and failure — no toast (progressive enhancement; a failed
  illustration just leaves the message text-only).
- **Read first:** `use-jobs-poller.ts` — `deriveKind` :28 (auto-register of unseen jobs :146,
  `handleTermination` :189); `jobs-store.ts` (`JobKind` union); bg B3's toast additions to
  `handleTermination` (landed by then); `query-client.ts:41-42` (`notebookChatSession(sessionId)`);
  coordinator frozen contract #6.
- **Spec:**
  - `jobs-store.ts`: add `'illustration'` to the `JobKind` union. No other store changes.
  - `deriveKind`: `case 'illustrate_message': return 'illustration'` (args carry `session_id`,
    `notebook_id`, `label` per the pinned contract — `serverRowToJob` already maps them).
  - `handleTermination`: on `completed` for `kind === 'illustration'` with a `sessionId`, invalidate
    `QUERY_KEYS.notebookChatSession(sessionId)` (same as `notebook_chat`). Ensure bg B3's
    completion/failure **toasts are NOT emitted** for `'illustration'` (guard by kind) — tray-only.
  - Nothing else: auto-register (:146), grace-period removal, and reload reconciliation already work
    for any active job.
- **Verify:** `npx tsc --noEmit` clean. With W1 integrated: send a diagram-worthy message → chat answer
  appears (chat job), then a beat later the diagram hydrates in WITHOUT manual refresh and WITHOUT a
  toast; the tray shows the illustration job while active; a failed/abstained job changes nothing
  visibly. Unit-level (pre-W1): a hand-inserted `illustrate_message` row in the active list derives
  kind `'illustration'` and triggers the invalidate on completion.

## F4 — FE-MERMAID: Mermaid renderer in the chat markdown pipeline
- **Owns:** `frontend/src/components/source/chat/Mermaid.tsx` (NEW),
  `frontend/src/components/source/chat/MarkdownCodeBlock.tsx`,
  `frontend/src/components/source/chat/ChatPanel.tsx`.
  **Deps:** none (renders any ` ```mermaid ` fence — independent of the backend).
- **Goal:** Render fenced ` ```mermaid ` blocks as diagrams, **safely**: `securityLevel:'strict'`,
  `mermaid.parse()` guard, **DOMPurify** on the SVG, **fallback-to-codeblock** on any failure (never a red
  error box). Serves both model-inline mermaid and the sidecar-appended diagram (P-3).
- **Read first:** `components/source/chat/ChatPanel.tsx` (`AIMessageContent`, the `ReactMarkdown`
  `components` map — `pre: MarkdownCodeBlock`, `remarkGfm`/`remarkMath`, `rehypeHighlight`/`rehypeKatex`);
  `components/source/chat/MarkdownCodeBlock.tsx` (`extractLanguage`/`extractText`). Coordinator D1 + P-3.
- **Spec:** add deps `mermaid` + `dompurify` (`cd frontend && npm install mermaid dompurify` — confirm
  versions vs `package.json`). New `components/source/chat/Mermaid.tsx` (`'use client'`): takes
  `chart: string`, runs `mermaid.initialize({ startOnLoad:false, securityLevel:'strict' })` once,
  `await mermaid.parse(chart)` then `mermaid.render(...)`, sanitizes the SVG with DOMPurify, and on any
  throw renders the raw source via the existing code-block UI. In the `components` map in `ChatPanel.tsx`,
  when a fenced block's language is `mermaid` (from `extractLanguage(node)`), render
  `<Mermaid chart={extractText(node)} />`; else fall through to `MarkdownCodeBlock` (cleanest: branch
  inside `MarkdownCodeBlock`/a small `CodeBlock`, keeping one `pre:` mapping). Handle light/dark via
  mermaid `theme`.
- **Verify:** an AI message with ` ```mermaid\ngraph TD; A-->B\n``` ` renders a diagram; an invalid block
  shows source as a code block (no red error); dark mode readable. `npm run build` clean.

## F5 — FE-POPOVER: side-chat Context popover + i18n
- **Owns:** `frontend/src/components/notebooks/chat/PoppedChatPanel.tsx`,
  `frontend/src/components/notebooks/chat/SideChatContextPopover.tsx` (NEW),
  `frontend/src/components/notebooks/workspace/DeepDiveWorkspace.tsx`,
  `frontend/src/lib/locales/*` (keys `chat.context*` only). **Deps:** F1, F2.
- **Goal:** A compact per-side-chat Context editor: opt sources/notes in/out (insights vs full), plus
  "Reset to notebook default" (→ `null`).
- **Read first:** `components/notebooks/chat/PoppedChatPanel.tsx` (header row; has `notebookId`/`session`/`chat`);
  `components/notebooks/workspace/DeepDiveWorkspace.tsx` (`useNotebookWorkspaceStrict()` exposes
  `sources`/`notes`; renders `PoppedChatPanel`); `ContextToggle.tsx`; `source-context.ts`
  (`applyBulkSourceContext`/`applyBulkNoteContext`/`bulkModeForSource`); the popover UI primitive; `locales/en-US/`.
- **Spec:**
  - Trigger: small icon button in `PoppedChatPanel`'s header row with a count badge of included
    sources/notes (mode ≠ `off`); quote-only default reads 0.
  - Body: title "Context for this chat"; a row per source/note using `ContextToggle` (off→insights→full,
    gated by `hasInsights`); bulk actions reusing `applyBulkSourceContext`/`applyBulkNoteContext`; a
    "Reset to notebook default" affordance.
  - Read state from `session.context_config` (object → render those modes; `null` → show the global
    selection as baseline, labelled "inheriting notebook default").
  - Write: each change → `chat.setSessionContextConfig(session.id, nextConfig)`; "Reset" →
    `chat.setSessionContextConfig(session.id, null)`.
  - i18n keys (`chat.contextForThisChat`, `chat.resetToNotebookDefault`, `chat.inheritingNotebookDefault`,
    `chat.contextIncludedCount`) across **all** locales (en-US reference).
- **Reuse:** `ContextToggle` + bulk helpers verbatim; existing popover primitive. Do NOT rebuild toggle
  logic; do NOT add an `insightsSnapshot` helper (quote-only default).
- **Verify:** `npx tsc --noEmit` + lint clean. **End-to-end (needs B1/B2/B4 integrated):** set a source to
  `full` in the drawer; spawn a side chat from a highlight → references resolve to the quote only; open the
  popover, opt that source in at `insights`, send → only insights cited; "Reset" → side chat follows the
  drawer again; reload → keeps its custom selection. Main dock chat still uses the global selection.

## F6 — FE-TOGGLE: per-notebook auto-illustrate toggle + i18n
- **Owns:** `frontend/src/components/notebooks/chat/SideChatDefaultMenu.tsx`,
  `frontend/src/components/notebooks/chat/ChatDock.tsx`,
  `frontend/src/components/notebooks/workspace/NotebookWorkspaceProvider.tsx`,
  `frontend/src/lib/locales/*` (keys `chat.autoIllustrate*` only). **Deps:** F1.
- **Goal:** A per-notebook auto-illustrate toggle (default ON) in the chat dock-header dropdown (P-2),
  persisting via the notebook update endpoint (B6 added the passthrough).
- **Read first:** `components/notebooks/chat/SideChatDefaultMenu.tsx` (dropdown pattern to mirror —
  `DropdownMenu` + label + helper + control) + how it's mounted in the dock header
  (`components/notebooks/chat/ChatDock.tsx`); `components/notebooks/workspace/NotebookWorkspaceProvider.tsx`
  (the `chat_tag_colors` update path: `notebooksApi.update(notebookId, {...})` +
  `queryClient.setQueryData(QUERY_KEYS.notebook(notebookId), …)`).
- **Spec:** in the dock-header dropdown (extend `SideChatDefaultMenu` or add a sibling control) add a
  checkbox/switch bound to `notebook.auto_illustrate ?? true`; on change call
  `notebooksApi.update(notebookId, { auto_illustrate: next })` and update the notebook cache (mirror
  tag-colors). i18n keys (`chat.autoIllustrate`, `chat.autoIllustrateHelper`) across all locales.
- **Reuse:** `SideChatDefaultMenu` structure; the `chat_tag_colors` update+cache pattern; Shadcn
  `Switch`/`Checkbox`; `useTranslation`.
- **Verify:** dock-header dropdown shows the toggle defaulting ON; turn OFF → `notebooksApi.update` fires,
  persists across reload. With it OFF, a chat turn submits no `illustrate_message` job (no illustration
  entry in the tray / `GET /commands/jobs` — once B6/W1 integrated). `npm run build` clean.

## Open Questions (frontend)
- **Q-quote-first-turn** — also prepend `quote` to the first user message? *Default: skip — the
  system-prompt seed already gives the model the quote each turn.*
- **Q-popover-home** — popover trigger in the header row vs composer toolbar. *Default: header row.*
- **Q-C-mermaid-ssr** — `mermaid` is browser-only. *Default: `'use client'` / dynamic import, no SSR.*
- **Q-C-toggle-host** — extend `SideChatDefaultMenu` vs sibling control. *Default: whatever keeps the
  dropdown cohesive.*
