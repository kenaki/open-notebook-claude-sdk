# Plan C — Workspace Layout + Dock (Notebook Multi-Chat Workspace)

> **One of 5 parallel plans.** Read `.claude/plans/notebook-chat-workspace.md` (the COORDINATOR) first
> for shared law: Decisions (esp. #2 layout, #8 model picker), Conventions, cross-plan status.
> **Chunks:** 6 (panel-track layout engine), 7 (multi-chat store + dock tabs + composer + model
> picker), 8 (pop-out / dock-back / drag-reorder / maximize / nesting). Frontend.
> **Dependencies:** **Plan A's Chunk 0** (theme tokens) must be ☑ landed before you start — you build
> panels with the new tokens. Do the chunks **in order** (6→7→8); each needs the previous.
> **Input artifact:** `design_handoff_notebook_chat/README.md` (Layout, Chat system, State Management).

## Coordination (same working tree, sequential landing)
- **Wait for:** Plan A row ☑ in coordinator (Chunk 0 token swap landed). Check before starting.
- **Files you introduce/own:** new `chat-workspace-store.ts`, new `PanelCard`/`PanelTrack` components,
  `app/(dashboard)/notebooks/[id]/page.tsx` (track rebuild), `notebooks/components/{SourcesColumn,
  NotesColumn,ChatColumn}.tsx` (port into panels).
- **Shared with Plan D (you go FIRST):** `components/source/ChatPanel.tsx` (you restructure for the
  dock; D extends it), `lib/types/api.ts` (you add chat-workspace types; D adds Citation/tool/media),
  `lib/hooks/useNotebookChat.ts` (you wire dock send; D adds citations/subchat/media). **Land C before
  D starts** so D extends a stable base.
- **Shared with Plan E:** `notebooks/[id]/page.tsx` (E adds mobile later) — fine, you go first.
- **Deps to add:** `react-resizable-panels` (Chunk 6), `@dnd-kit/core` (Chunk 8, Open Q-dnd default).
- When done: update coordinator Cross-plan status row "C" → ☑ + Changelog.

## Resume prompt (fresh chat)
> Execute Plan C (Workspace Layout + Dock) of the Notebook Multi-Chat Workspace. First confirm Plan A
> is ☑ in the coordinator. Read `.claude/plans/ncw-c-workspace-layout.md` and the coordinator
> `.claude/plans/notebook-chat-workspace.md` in full (plus the handoff README). Do the next unstarted
> chunk in order (6→7→8), verify it, update this plan's Status + the coordinator's Cross-plan
> status/Changelog, and tell me when it's safe to clear context.

## Status
| Chunk | Title | Status | Notes |
|------:|-------|--------|-------|
| 6 | Panel-track layout engine (resizable Sources/Notes/Dock cards) | ☑ done | Landed `claude-agent-integration`. See notes below. |
| 7 | Multi-chat store + dock tabs + composer + in-dock model picker | ☑ done | Landed `claude-agent-integration`. See notes below. |
| 8 | Pop-out / dock-back / drag-reorder / maximize / nesting order | ☑ done | Landed `claude-agent-integration`. See notes below. |

**Chunk 8 landed (2026-06-22) — Plan C COMPLETE:**
- **Two decisions surfaced & answered (human):** (1) per-popped-chat messages → **multiplex one hook**
  (not one-hook-per-chat); (2) **add `@dnd-kit`** (Q-dnd default). Installed `@dnd-kit/core` +
  `@dnd-kit/sortable` + `@dnd-kit/utilities` (`npm install` from `frontend/`).
- **Hook multiplexed + lifted (`useNotebookChat.ts`, shared file — still stable for Plan D):** new
  optional `visibleSessionIds` param (dock-active + popped). Replaced the single `messages` useState +
  `currentSession` query with **`useQueries`** over `liveSessionIds` (currentSession ∪ visible); per-session
  optimistic updates via `queryClient.setQueryData` on each session's key (no local mirror); per-session
  `sendingBySession`. New exports **`getMessages(id)` / `getIsSending(id)` / `sendMessageTo(id,msg)`**;
  back-compat `messages`/`isSending`/`sendMessage` now delegate to the active session. delete-mutation
  `removeQueries` the session key. **The hook is now instantiated ONCE in `page.tsx`** and passed to the
  dock AND every popped panel (also fixes a latent mobile double-mount — both layout branches are now
  `isDesktop`-gated, only one mounts).
- **Stores:** `notebook-columns-store` `maximized` widened **`PanelId|null` → `string|null`** (can name a
  popped chat by session id); `toggleMaximized`/`setMaximized` take `string`. `chat-workspace-store` gained
  **`panelOrder: string[]`** (anchor display order, default `FIXED_PANEL_IDS=['sources','notes','dock']`,
  exported) maintained by `setDocked` (pop→append / dock→remove) + pruned in `syncChats`; new
  `reorderPanels`. Still **ephemeral (not persisted)**.
- **`PanelCard` is now sortable** (`@dnd-kit useSortable`): added `id` prop + a **left-edge grip handle**
  (hover-revealed `GripVertical`, drag listeners) to reorder; transform/transition applied; **self-hide
  removed** — the page decides visibility (skips hidden cards) so the sortable `items` list always matches
  what's mounted. Resize handle (right edge) + double-click-maximize unchanged. **Deviation (documented):**
  handoff says "drag the header"; headers across Sources/Notes/Dock/popped are heterogeneous, so reorder is
  driven by a dedicated left-edge grip (mirrors the right-edge resize affordance) — cleaner than wiring a
  handle into every child header.
- **New `components/notebooks/PoppedChatPanel.tsx`:** a popped chat = a `PanelCard` whose child is the same
  **`ChatPanel` dock variant** (`composerMaxHeight={120}` per handoff, controlled `draft`/`onDraftChange`
  from the store) wrapped in a header (dock-back ⤵ `ArrowLeftToLine`, close ✕, ≥1-enforced) + a
  **"DISCUSSING THIS PASSAGE" banner** (accent-soft, 3px accent left-border, quote icon) shown when `quote`
  is set. Messages/send go through the multiplexed hook for **this session's id**.
- **`ChatDock.tsx`:** now receives the **`chat` hook** (not pre-extracted messages) + computes its own
  **docked-only** tab list (popped chats leave the strip); active tab repoints to a docked session via
  effect when the current one is popped. **Pop-out (↗) enabled** → `setDocked(id,false)` (+ hands the dock
  to the next docked chat). Tabs are a **`SortableContext`** (`SortableTab`, distance-activated so clicks
  still switch; pop-out/close buttons `stopPropagation` on pointer-down). Exports `TAB_DND_PREFIX`. New
  `enablePopOut` prop (default true) — **false on mobile** (no track to render popped panels; mobile is
  Plan E's).
- **Page (`notebooks/[id]/page.tsx`):** wraps both layout branches in ONE **`DndContext`** (PointerSensor,
  6px activation; `closestCenter`). Computes the **derived display order** (handoff algorithm: anchors =
  fixed panels + popped chats w/o a present parent; recursive `layout` inserts `childChatsOf` right after
  each; orphan promotion; safety-append) and renders cards **in that DOM order** inside a horizontal
  `SortableContext` (no CSS `order` needed). **Maximize** focus-set computed here (focused + descendants
  visible, rest not rendered; stale id cleared). `onDragEnd` routes: `tab:`→`popzone` = pop, `tab:`↔`tab:` =
  reorder `order`, panel↔panel = `reorderPanels`. **`PopZone`** dashed droppable ("drop to open side by
  side") shown only mid tab-drag. `parentId`/`quote` are **always null until Plan D** → every popped chat
  is a top-level anchor today, but the nesting algorithm + banner + passage empty-state are built so D's
  sub-chats slot in **right of their parent for free** (orphan fallback included).
- **i18n (append-only, all 14 locales):** added `chat.{dockBack, dropToPopOut, passageEmptyTitle,
  passageEmptyHelper}`. Parity ✓ across all 14.
- **Test:** `ChatColumn.test.tsx` updated — ChatColumn is now **presentational** (receives `chat` +
  `contextStats` + `loading`/`error`, no longer creates the hook); test passes a chat mock. 2/2. Restored
  the `chat.unableToLoadChat` error branch (gated by a new `error` prop) so my refactor doesn't orphan that
  key.
- **Verify:** `npm run build` ✓ green; `eslint` ✓ clean on all touched files; `ChatColumn` 2/2; i18n
  **parity ✓ all 14**. *Pre-existing (not mine):* the unused-key test still flags **`navigation.collect`/
  `navigation.manage`** (Plan A debt) — left untouched per the coordinator rule. on-frontend restarted (HTTP
  307 ✓). Interactive checks to confirm in the running app: pop a tab via ↗ and via drag→drop-zone; dock
  back; reorder tabs (drag) + panels (left-edge grip); double-click maximize a popped chat; multi-chat
  side-by-side message streams independent.
- **Not done (deferred, documented):** sub-chat **creation** (selection → "Chat about this") + populating
  `parentId`/`quote` = **Plan D** (the render-side nesting/banner/empty-state are ready). Mobile track +
  mobile pop-out = **Plan E** (Q-mobile). Per-chat model override = deferred (Decision 8).

**Chunk 7 landed (2026-06-22):**
- **Store (new):** `lib/stores/chat-workspace-store.ts` — `useChatWorkspaceStore` (NOT persisted;
  ephemeral client layer over sessions per Decision 5/8). State: `chats: Record<id, WorkspaceChat>`,
  `order: string[]`, `activeChatId`. Actions: `syncChats(ids)` (reconcile vs live session list —
  add/drop/append, keep active valid), `setActiveChat`, `setDraft`, `removeChat`, plus Chunk-8 stubs
  `setDocked`/`setChatWidth`/`reorder`. `WorkspaceChat`/`ChatPendingMedia` types added to
  `lib/types/api.ts` (`docked`/`width`/`draft`/`pending` client-only; `parentId`/`quote` mirror Plan B's
  persisted sub-chat fields — **frozen base for Plan D**). `POPPED_CHAT_DEFAULT_WIDTH=480` exported.
- **Dock (new):** `components/notebooks/ChatDock.tsx` — the Chat Dock panel (provides its own panel
  shell: `bg-card border rounded-xl shadow-[var(--shadow)]`, matching Sources/Notes cards). **Dock
  header** = global model picker (`Select` bound to `useClaudeAgentModel`/`useUpdateClaudeAgentModel`,
  Decision 8 — writes the **global** `claude_agent` config, reflected in Settings; `''` follow-default
  mapped to a `__default__` sentinel since Radix forbids empty-value items) + **context-meter pill**
  ("N sources · M notes · k tokens" from `ChatColumn`'s `contextStats`; tokens shown as `k` ≥1000).
  **Tab strip** = one tab per session (order from store; static this chunk), active highlight, **close
  (✕) enforces ≥1** (disabled on the last tab), **pop-out (↗) rendered disabled — functional in
  Chunk 8**, and a **"+"** new-chat button (eager `createSession(newChat)`). Empty session list shows a
  single placeholder "New chat" tab. Only the active tab renders its conversation.
- **ChatPanel re-skin (shared file — kept stable for Plan D):** `components/source/ChatPanel.tsx` gained
  an additive **`variant: 'standalone' | 'dock'`** (default standalone → **source chat unchanged**).
  Dock variant drops the card chrome / internal header / model selector / context indicators (the dock
  supplies them) and shows the ⌘↵ hint line. Shared reskin (both variants): **bubbles** (user
  `14px 14px 4px 14px`, AI mirrored `14px 14px 14px 4px`; `bg-primary`/`bg-muted`, avatars removed),
  **auto-grow composer** (ref + effect, cap 140 dock / 100 standalone, then scrolls; ⌘↵/Ctrl+↵ sends),
  **empty-state** (sparkle in `bg-accent-soft` + title + helper + optional 3 suggestion buttons that send
  presets). New optional props: `draft`/`onDraftChange` (controlled per-chat composer; uncontrolled
  fallback for source chat), `composerMaxHeight`, `emptyStateTitle`/`emptyStateHelper`, `suggestions`.
- **Hook (shared file):** added **`renameSession(id, title)`** to `lib/hooks/useNotebookChat.ts` — a
  silent `chatApi.updateSession` + invalidate (no toast), used by the dock to auto-derive a chat title
  from its first message when the chat is still named "New chat". `ChatColumn.tsx` now renders `<ChatDock>`
  (was `<ChatPanel>`); it still owns `useNotebookChat` + `contextStats`.
- **i18n (append-only, all 14 locales):** added `chat.{newChat,popOut,closeChat,emptyTitle,emptyHelper,
  suggestionSummarize,suggestionQuestions,suggestionConnections,meterSources,meterNotes,meterTokens}`.
  Removed the now-orphaned `chat.chatWithNotebook` (its only referent, the dock's old title, is gone) from
  all 14 — kept the locale set in parity.
- **Test:** `ChatColumn.test.tsx` mock switched `@/components/source/ChatPanel` → `@/components/notebooks/
  ChatDock` (ChatColumn now renders the dock). Still 2/2.
- **Verify:** `npm run build` ✓ green; `eslint` ✓ clean on all touched components/store/hook;
  `ChatColumn.test.tsx` ✓ 2/2; i18n **parity ✓ all 13 locales** + unused-key detection ✓ for all my keys.
  *Pre-existing (not Chunk 7):* the unused-key test still flags `navigation.collect`/`navigation.manage`
  — orphaned by **Plan A's** sidebar reskin (referenced only in `HEAD`); left untouched per the
  coordinator's "never delete another plan's keys" rule. Interactive checks (multi-tab switch, model
  dropdown ↔ Settings, meter counts, suggestions, ⌘↵) to confirm in the running app.
- **Not done here (Chunk 8):** pop-out / dock-back, drag-reorder of tabs/panels, derived nesting order.
  Media composer attach UI (Plan D) and citation/tool-use bubble rendering (Plan D) intentionally deferred;
  `ChatPanel` dock body + `ChatDock` are the stable base they extend.

**Chunk 6 landed (2026-06-22):**
- **Dep deviation (documented):** did **not** add `react-resizable-panels`. Its model forces panels to
  sum to 100% of a fixed container; the handoff wants **independent pixel-width** panels in an
  `overflow-x:auto` track that scrolls when overflowed. Implemented a **custom pointer-based resize
  handle** instead (no new dependency). Chunk 8 still plans `@dnd-kit/core` for drag-reorder/pop-out.
- **Store:** extended `lib/stores/notebook-columns-store.ts` (kept the name + persist key
  `notebook-columns-storage`; shallow-merge tolerates old persisted state) with
  `widths{sources:296,notes:316,dock:520}`, `setWidth` (clamps 240–980), `maximized: PanelId|null`,
  `toggleMaximized`/`setMaximized`. Exported `PanelId`, `PANEL_DEFAULT_WIDTHS`, `PANEL_MIN/MAX_WIDTH`.
- **New components:** `components/notebooks/PanelTrack.tsx` (horizontal `flex` row, `gap-4`,
  `overflow-x-auto`, `items-stretch`; caller supplies track padding `px-6 pt-4 pb-[18px]`) and
  `components/notebooks/PanelCard.tsx` (fixed-px width via `flexShrink:0`; right-edge pointer-capture
  resize handle clamped 240–980; double-click maximize → `flex:1 1 0%` and siblings return `null`
  (`anyMaximized`); guards double-click against buttons/inputs/links/text-selection; `minimized` lets
  the existing collapse chip show at natural width with no resize).
- **Page:** rebuilt the desktop branch of `app/(dashboard)/notebooks/[id]/page.tsx` to render
  `<PanelTrack>` with three `<PanelCard>`s wrapping the **unchanged** `SourcesColumn`/`NotesColumn`/
  `ChatColumn` (no column refactor → mobile tab path untouched, kept on its own `{!isDesktop}` branch
  with `p-6`). Removed the now-unused `cn` import. Minimize-to-chip is the **existing**
  `CollapsibleColumn`/`notebook-columns-store` collapse (already wired into Sources/Notes), surfaced via
  `minimized={sourcesCollapsed}` etc. Chat dock is not minimizable.
- **Not done here (by design, deferred to later chunks):** the handoff page-header
  (title·badge·counts·collapsed-chips·theme toggle) still uses the old `NotebookHeader`; the chat panel
  still renders its own `ChatPanel` card chrome (Chunk 7 restructures it for the dock + reskins
  bubbles/composer/empty-state + adds the dock-header model picker & context meter). Double-click
  maximize works on Sources/Notes/Dock card bodies/headers; no separate maximize button (would collide
  with the existing add/collapse controls top-right).
- **Verify:** `npm run build` ✓ green; `eslint` ✓ clean on all four touched files; `ChatColumn.test.tsx`
  ✓ 2/2. Interactive checks (drag-resize within 240–980, double-click maximize/restore, minimize chips,
  horizontal track scroll on overflow) to confirm in the running app.

---

### Chunk 6 — Panel-track layout engine
- **Goal:** The notebook page becomes the handoff **panel track**: a horizontal, independently-
  scrolling row of rounded panel cards (Sources, Notes, Chat Dock) that are **width-resizable**
  (240–980px clamp) and **maximizable** (double-click header). Sources/Notes can minimize to a chip.
  (Drag-reorder + pop-out land in Chunk 8.)
- **Read first:** handoff README "Layout" (24–46) + "Interactions" (136–145) + sizing (203–207);
  `app/(dashboard)/notebooks/[id]/page.tsx` (current flex layout); `notebooks/components/
  SourcesColumn.tsx`, `NotesColumn.tsx`, `ChatColumn.tsx`; `components/notebooks/CollapsibleColumn.tsx`;
  `lib/stores/notebook-columns-store.ts`.
- **Spec / exact values:** panel shell `border-radius:12px; 1px border; var(--shadow); flex column;
  overflow hidden`. Default widths Sources 296 / Notes 316 / Dock 520. Track `gap:16px; padding:16px
  24px 18px; overflow-x:auto`. Resize clamp **240–980px**.
- **Reuse:** install **`react-resizable-panels`** (none present) for resize; re-skin existing
  Sources/Notes/Chat content into the panel shell; extend `notebook-columns-store` (or a new
  `workspace-store`) for `widths{}` + `maximized` + `collapsed{}`.
- **Steps:** (1) add the dep; (2) build a `PanelCard` shell + a `PanelTrack` container; (3) port
  Sources/Notes/Chat content into cards; (4) per-panel resize handles with the clamp persisted to the
  store; (5) double-click header → maximize (focused panel flexes to fill, others hide per spec);
  (6) Sources/Notes minimize-to-chip.
- **Verify:** the three panels render as a horizontal resizable track; drag edges resize within
  240–980; double-click maximizes/restores; minimize chips work; track scrolls horizontally when
  overflowed. `npm run build` passes.

### Chunk 7 — Multi-chat store + dock tabs + composer + in-dock model picker
- **Goal:** The Chat Dock holds a **flat list of chats** as tabs (only the active tab renders its
  conversation); the composer + message bubbles + empty-state + context meter match the handoff; the
  dock header has the **model picker** (bound to the existing `claude_agent` config) and a context
  meter pill. Single-dock only (pop-out in Chunk 8).
- **Read first:** handoff README "Chat system" (48–126); `components/source/ChatPanel.tsx` (full),
  `SessionManager.tsx`, `MessageActions.tsx`; `lib/hooks/useNotebookChat.ts`; `lib/types/api.ts`
  (chat types); `lib/hooks/use-models.ts` (`useClaudeAgentModel`, `useUpdateClaudeAgentModel`);
  `components/common/ModelSelector.tsx`.
- **Spec / exact values:** chat data model (README 52–82) — `{id,title,docked,width,draft,pending,
  messages,parentId?,quote?}`; bubble radius `14px 14px 4px 14px`; composer auto-grow cap 140px (dock);
  ⌘↵/Ctrl+↵ sends; empty-state = sparkle + title + helper + 3 suggestion buttons.
- **Reuse:** map "chats" onto existing **sessions** (a chat = a session; `messages` from
  `useNotebookChat`); reuse `useClaudeAgentModel`/`useUpdateClaudeAgentModel` for the picker
  (Decision 8 — global value); reuse `MessageActions`, the markdown renderer.
- **Steps:** (1) new Zustand `chat-workspace-store` (`chats[]`, `activeChatId`, `order`, `widths`,
  client-only `docked/width/draft/pending`); (2) Dock panel with reorderable **tabs** (reorder in
  Chunk 8 — static order here), pop-out/close buttons (close enforces ≥1); (3) re-skin `ChatPanel`
  bubbles + auto-grow composer + empty-state + suggestions; (4) dock-header model dropdown +
  context-meter pill ("N sources · M notes · k tokens" from `ChatColumn`'s existing stats).
- **Verify:** multiple chats appear as dock tabs; switching tabs swaps the conversation; composer
  sends (button + ⌘↵); model dropdown reads/writes the claude-agent config (reflected in Settings);
  context meter shows real counts; empty-state + suggestions work. `npm run build` passes.

### Chunk 8 — Pop-out / dock-back / drag-reorder / maximize / nesting order
- **Goal:** Chats can **pop out** to standalone side-by-side panels in the track and **dock back**;
  dock tabs and panels are **drag-reorderable**; the panel display **order is computed** (anchors +
  recursive `layout()` so a child sits immediately right of its parent; orphan fallback). Maximize
  focus-set behaves per spec.
- **Read first:** handoff README "Docked vs popped" (84–88), "Ordering/nesting" (100–105), "State
  Management" (146–152); the Chunk 6 `PanelTrack`/store + Chunk 7 `chat-workspace-store`.
- **Spec / exact values:** popped chat default width 480px; drag-out reveals a dashed drop zone ("Drop
  here to open side by side"); order computed from anchors `[sources,notes,dock]` + popped chats w/o a
  present parent; `childChatsOf` = popped chats whose `parentId` matches; assign CSS `order`.
- **Reuse:** a dnd primitive (add `@dnd-kit/core` or use HTML5 drag — Open Q-dnd, default `@dnd-kit`);
  the Chunk 6 resize/maximize plumbing.
- **Steps:** (1) pop-out (`docked:true→false`) renders the chat as its own `PanelCard` with header
  (dock-back ⤵, close ✕) + composer; (2) dock-back inverse; (3) drag tab to drop-zone → pop;
  (4) drag-reorder tabs + panels; (5) implement the derived `order` algorithm (anchors + recursive
  `layout`, orphan promotion) feeding CSS `order`.
- **Verify:** pop a chat → side-by-side panel; dock it back; drag a tab out via the drop-zone; reorder
  tabs/panels; with a sub-chat present (after Plan D Chunk 11) it renders immediately right of its
  parent and survives parent close (orphan fallback). `npm run build` passes.

#### Notes for Chunk 8 (flagged from the Chunk 7 build — read these first)
- **The pop-out button already exists, just disabled.** `ChatDock.tsx` renders a per-tab `ArrowUpRight`
  (↗) button with `disabled` + `opacity-30` + `title={t('chat.popOut')}`. Chunk 8 = enable it and wire
  `onClick` → `useChatWorkspaceStore.setDocked(id, false)` (the action is **already implemented** in the
  store, currently unused). i18n key `chat.popOut` is **already present in all 14 locales**.
- **The store's Chunk-8 hooks are already in place** (`chat-workspace-store.ts`): `setDocked(id,docked)`,
  `setChatWidth(id,width)`, `reorder(order[])`, and per-chat `width` (default `POPPED_CHAT_DEFAULT_WIDTH
  = 480`, exported). The store is **ephemeral (NOT persisted)** — popped/order/width state resets on
  reload by design; keep it that way unless you deliberately add persistence.
- **`order` here is the store's tab order, not the CSS display order.** The handoff's derived
  display-order algorithm (anchors `[sources,notes,dock]` + recursive `layout()` + orphan promotion) is
  **not built yet** — compute it at render time in `notebooks/[id]/page.tsx`, feeding CSS `order` to the
  `PanelCard`s. Don't store it. `parentId`/`quote` on `WorkspaceChat` exist but are **always null until
  Plan D** (sub-chats) — so `childChatsOf` is empty in practice this chunk; build the algorithm anyway so
  D's sub-chats slot in for free.
- **Maximize already half-works.** `notebook-columns-store` has `maximized: PanelId|null` but `PanelId`
  is only `'sources'|'notes'|'dock'` — it can't name a popped chat. To maximize a popped chat you'll need
  to widen the maximize identity (e.g. `maximized: string|null` keyed by panelId **or** chatId) and teach
  `PanelCard`'s `anyMaximized`/`maximized` props + the page's order/visibility logic about chat ids. Spec:
  focused panel fills, **its sub-chats stay visible at fixed width**, everything else hides.
- **Popped chat = reuse the dock body.** A popped chat should render as a `PanelCard` whose child is the
  **same `ChatPanel` dock variant** the dock uses (`variant="dock"`, controlled `draft`/`onDraftChange`
  from the store, `composerMaxHeight={120}` per handoff — popped cap is 120, dock is 140), wrapped in a
  small header (dock-back ⤵, close ✕). Each popped chat needs its **own messages** — note `useNotebookChat`
  is a **single instance in `ChatColumn`** tracking one `currentSessionId`; rendering N popped
  conversations side-by-side means N independent message streams. Decide the approach early: either lift
  to one `useNotebookChat` per visible chat (cleanest), or extend the hook to fetch/cache messages per
  session id. **This is the main architectural decision of Chunk 8 — surface it before coding.**
- **`PanelCard` resize/maximize plumbing is reusable as-is** (pointer-capture handle, 240–980 clamp,
  double-click guards against buttons/inputs/text-selection). The drag-**reorder** + drop-zone is new and
  is where the dnd primitive (Q-dnd, default `@dnd-kit/core`) comes in — `PanelTrack` is a plain flex row
  today with no drag wiring.
- **Close (✕) is already functional + ≥1-enforced** in the dock; mirror the same guard on popped-panel
  close. Closing a popped chat that has children → those children orphan-promote (don't disappear).

## Completion
When all three chunks are ☑: update the coordinator's Cross-plan status (row C → ☑) + Changelog,
announce "✅ Plan C complete — safe to clear context. Plan D may now start (dock + backend ready)." stop.