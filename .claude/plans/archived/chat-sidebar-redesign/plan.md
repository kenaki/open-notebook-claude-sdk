# Notebook Chat Workspace — Sidebar Redesign — Feature Development Doc

> **Living master plan & single source of truth.** Written so one session can execute the whole plan
> end-to-end. **Run mode: SINGLE SESSION, all 5 chunks straight through** — the chunks are sequential
> review/verify checkpoints, NOT separate sessions. Verify + commit after each chunk, then continue to
> the next; do **not** clear context between chunks. Keep the Status table + Changelog current.
> **Location:** `.claude/plans/chat-sidebar-redesign/plan.md` while active → moved to
> `.claude/plans/archived/chat-sidebar-redesign/` once every chunk is done.

---

## SESSION HANDOFF — resume here
**State at handoff (2026-06-22):** Planning complete. No code yet. Branch `feature/multipanelchat`.
**Run mode:** ALL 5 chunks in ONE session, in order. After each chunk: verify (frontend typecheck/lint),
mark it ☑ + Changelog line, commit, then continue to the next chunk (no context clear). Archive when
Chunk 5 lands.
**Paste-able resume prompt (run in one chat):**
> Execute the Notebook Chat Workspace sidebar redesign. Read
> `.claude/plans/chat-sidebar-redesign/plan.md` in full, then implement **all 5 chunks in order in this
> one session**. After each chunk: verify (frontend typecheck/lint), update the doc's Status table +
> Changelog, and commit. Pause only if a chunk's verify fails or an Open Question blocks you. After
> Chunk 5, run the end-to-end verification and archive the feature directory per the Completion section.

---

## How to use this document (read first)
1. Reuse before create — smallest faithful diff. The data model & APIs already exist; this is almost
   entirely a frontend refactor. Never invent a value → Open Questions.
2. **Run all 5 chunks in one session, in order.** Per-chunk workflow: read referenced files → implement
   → verify → update Status + Changelog → note new Open Questions → commit → **continue to the next
   chunk**. Do NOT clear context between chunks.
3. Every UI string MUST get an i18n key in `frontend/src/lib/locales/en-US/index.ts` (see Conventions).
4. Each chunk must leave the app in a working state (the dock still works after every chunk) — they're
   ordered so the app stays runnable at each checkpoint.

### Per-chunk checkpoints (sequential, same session)
At the end of each chunk: (1) verify (typecheck/lint), (2) mark ☑ + Changelog line, (3) record
decisions/Open Questions, (4) commit, (5) move on to the next chunk. **Pause only** if a chunk's verify
fails, or an Open Question / decision genuinely blocks progress.

### Completion & archival
When the **final build-now chunk (Chunk 5) is ☑ done**: append a Changelog line ("All chunks complete —
archived 2026-..."), then **move the whole feature directory** to
`.claude/plans/archived/chat-sidebar-redesign/`
(`mkdir -p .claude/plans/archived && mv .claude/plans/chat-sidebar-redesign .claude/plans/archived/`),
and tell the user the plan is complete and archived.

### Status table
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| 1 | Foundations: promote helper + types + i18n (additive) | ☑ done | opus session | no behavior change; tsc+lint clean |
| 2 | ChatSidebar + explicit-open visibility model | ☑ done | opus session | tab strip replaced by sidebar rail; tsc+lint clean; frontend compiles |
| 3 | Hide vs Trash (X = hide, 🗑 = delete) | ☑ done | opus session | X=hide (closeChat), new DeleteChatButton confirm-dialog; tsc+lint clean |
| 4 | Side-chat scoping + "side chats" control | ☑ done | opus session | SideChatsMenu in dock header; sub-chat create now pops; tsc+lint clean |
| 5 | Promote ("collapse") side chat → main | ☑ done | opus session | promote button in popped header; syncChats reconciles parent/quote; tsc+lint clean |
| — | Deferred niceties | ⊘ deferred | | see Deferred section |

Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

### Changelog
- **2026-06-22 — Chunk 1 done.** Added `parent_session_id?`/`quote?` to
  `UpdateNotebookChatSessionRequest` (api.ts); added silent `promoteToMain(sessionId)` +
  memoized `mainSessions`/`sideSessionsOf` selectors to `useNotebookChat` and exported them; added
  10 sidebar i18n keys to the `chat` section. No behavior change; `tsc --noEmit` + `eslint` clean.
  Note: the working tree already carried the side-chat-default-model groundwork (chat-defaults-store,
  ChatModelPicker, SideChatDefaultMenu, createSidePanel, setSessionModelOverride) — the plan's listed
  reuse primitives — which is bundled into the Chunk 1 commit as baseline.
- **2026-06-22 — Chunk 2 done.** Reworked `chat-workspace-store` to an explicit
  open/closed visibility model: added `open` to `WorkspaceChat`; `syncChats` now creates CLOSED
  entries for new sessions and auto-opens only the most-recent main on first load; added
  `openChat`/`popChat`/`closeChat`, dropped `setActiveChat`/`setDocked`/`reorder`. New
  `ChatSidebar.tsx` (searchable, recency-ordered MAIN-chat list + inline rename + "+"). `ChatDock`
  rewritten: tab strip gone, now a sidebar rail + active-main conversation. `createSession` is now
  async, returns the session, and creates a MAIN chat (global default model, not the side-chat
  default). page.tsx: removed tab DnD / PopZone / `TAB_DND_PREFIX`; `poppedIds` now requires `open`;
  dock-back → `openChat`; pending side-chat pop → `popChat`. tsc+lint clean; frontend dev server
  compiles and serves the notebook page. Note: X/trash still delete (Chunk 3 repoints X → hide).
- **2026-06-22 — Chunk 3 done.** Split hide vs delete. New shared
  `DeleteChatButton.tsx` (trash icon + `AlertDialog` confirm using `deleteChatConfirm`, destructive
  action) wired into the sidebar row (main chats) and the popped-panel header (side chats). Popped
  panel's X is now a non-destructive **hide**: `PoppedChatPanel` `onClose` repointed in page.tsx from
  `chat.deleteSession` → `closeChat(token)`, with a new `onDelete` prop → `chat.deleteSession`. Dropped
  the `canClose` "keep at least one chat" guard (hiding the last chat is fine — sidebar still lists it).
  X tooltip → `chat.hideChat`. tsc clean; lint only pre-existing baseline warnings (none in new files).
- **2026-06-22 — Chunk 4 done.** New `SideChatsMenu.tsx` (DropdownMenu, `sideChatsCount` label,
  open-dot indicator) rendered in the dock header for the active main via `chat.sideSessionsOf(
  activeMainId)`; clicking a row → `openChat` (pops the side chat). Sub-chat hydration was already gated
  on open-state by Chunk 2's `syncChats` (new side chats land closed), so the only page change was
  repointing `handleCreateSubChat` to also `setPendingPopId` — without it, post-Chunk-2 passage→sub-chat
  creation would land closed and never surface. tsc clean; lint unchanged baseline.
- **2026-06-22 — Chunk 5 done.** Added a promote control (`ArrowUpToLine`, `promoteToMain` label) to
  the `PoppedChatPanel` header, shown only for side chats (`workspaceChat.parentId`). New `onPromote`
  prop wired in page.tsx → `chat.promoteToMain(token)`. Critically, `syncChats` now refreshes the
  server-owned `parentId`/`quote` on existing store entries (previously kept verbatim) so a promote
  reconciles side → main: the "discussing passage" banner + promote button (both read parentId/quote)
  disappear and the chat surfaces in the sidebar. tsc clean; lint unchanged baseline.
- **2026-06-22 — All chunks complete — archived 2026-06-22.** Chunks 1–5 landed on
  `feature/multipanelchat`; frontend dev server (on-frontend) restarted and serves the notebook page
  clean. Plan moved to `.claude/plans/archived/chat-sidebar-redesign/`.

---

## Context — why
Today a notebook's chats are crammed into a **horizontal tab strip** inside `ChatDock`
(`frontend/src/components/notebooks/ChatDock.tsx`). This does not scale — imagine 20 chapter-chats as
tabs. The DB already supports unlimited persistent chats per notebook (`chat_session` records linked to
the notebook via the `refers_to` graph edge), and all session CRUD APIs already exist; the **only**
missing thing is a scalable navigator.

**This effort (build-now):** replace the tab strip with a **sidebar chat library** that lists only MAIN
chats; keep the existing multi-panel dock (popped panels) and side/nested chats; add a non-destructive
**hide** (X) vs **delete** (trash) distinction; and let a side chat be **promoted ("collapsed") to a
main chat**. Mostly frontend; one tiny frontend-type addition. No backend/LangGraph/data-model changes.

**Explicitly OUT OF SCOPE (do not build):** annotation primitive, persistent highlight rendering,
bidirectional highlight↔chat hyperlinks, source-material highlighting, "chats that discuss this source"
view. The existing transient passage-selection → sub-chat creation (`PassageSelectionMenu`,
`data-chat-scope`) stays as-is.

## Decisions log
| # | Question | Decision |
|--:|----------|----------|
| 1 | How to navigate many chats | **Sidebar chat library** (flat, recency-sorted, searchable). Grouped/folders deferred. |
| 2 | Keep multi-panel side-by-side? | **Yes** — keep `PanelTrack`/`PanelCard`/`PoppedChatPanel`/multiplexed `useNotebookChat`. Only the dock **tab strip** is replaced. |
| 3 | What appears in the sidebar | **Main chats only** = sessions with `parent_session_id == null`. Side chats NEVER appear in the sidebar. |
| 4 | Where side chats live | Under their parent main chat; shown (scoped) when that main is the active/open chat: sessions where `parent_session_id == activeMainId`. |
| 5 | Reaching hidden side chats | Each open main chat shows a small **"side chats (n)" control** listing ALL its side chats incl. hidden ones, click to reopen. |
| 6 | X button semantics | **X = HIDE** (non-destructive view state; chat stays in DB). |
| 7 | Delete semantics | A separate **trash icon = DELETE** permanently (existing `deleteSession`). |
| 8 | "Collapse" a side chat | **Promote to main** = clear `parent_session_id` (+ `quote`) via existing `updateSession`/PUT. It then appears in the sidebar. |
| 9 | Side-chat persistence | Side chats persist by default — nothing auto-discarded. |

### Decision Register
> Severity & gating per `~/.claude/skills/severity-model.md`. S1 trivial · S2 low · S3 significant · S4 critical.
| ID | Decision | Severity (why) | Status | Chosen / default |
|----|----------|----------------|--------|------------------|
| P-nav | Sidebar library replaces the tab strip | S3 (cross-cutting UI rework) | resolved (user) | Sidebar chat list |
| P-multipanel | Keep popped multi-panel | S2 | resolved (user) | Kept |
| P-visibility | Rework store from "auto-dock every session" → **explicit open/closed** visibility | S3 (touches store + dock + page; behavior change) | resolved (auto) | Explicit-open model (Chunk 2) |
| P-hide-trash | X hides; trash deletes | S2 (reversible) | resolved (user) | Hide vs delete split |
| P-promote | Promote via clearing `parent_session_id` on existing PUT | S2 | resolved (verified API) | No backend work |
| P-sidebar-placement | Sidebar as a left rail INSIDE the existing `dock` PanelCard (vs a new fixed track panel) | S2 (reversible layout) | resolved (default) | Left rail inside the dock card — leaves PanelTrack/displayOrder untouched. Revisit if cramped. |

## Conventions / translation notes
- **i18n:** all visible strings go through `t('chat.<key>')`; add keys to
  `frontend/src/lib/locales/en-US/index.ts` (the `chat` section — existing keys: `newChat`, `popOut`,
  `closeChat`, `dockBack`, `discussingPassage`, `meterSources`, etc.). Other locale files can stay
  English-fallback for now (project pattern).
- **State:** Zustand store `chat-workspace-store.ts` is **currently NOT persisted** (it re-syncs from
  the live session list each mount via `syncChats`). Visibility state added here is therefore ephemeral
  per the default (see Q-hide-persistence).
- **Styling:** Tailwind + the project's CSS vars (`bg-card`, `border-border`, `bg-accent`,
  `text-muted-foreground`, `shadow-[var(--shadow)]`). Match `ChatDock`/`PoppedChatPanel` chrome.
- **Icons:** `lucide-react` (already used: `Plus`, `X`, `ArrowUpRight`, `ArrowLeftToLine`, `Quote`).
  Use `Trash2` for delete, `PanelLeft`/`MessagesSquare` for sidebar/side-chats as needed.
- **DnD:** `@dnd-kit` is wired at the page level (single `DndContext`); don't add a second one.

---

## Chunks

### Chunk 1 — Foundations: promote helper + types + i18n (additive, no behavior change)
- **Goal:** Add the primitives later chunks need, without changing any current behavior. App looks
  identical after this chunk.
- **Read first:** `frontend/src/lib/types/api.ts` (L279–282), `frontend/src/lib/hooks/useNotebookChat.ts`
  (L329–339 `updateSession`, L397–405 `renameSession` pattern), `frontend/src/lib/locales/en-US/index.ts`
  (`chat` section).
- **Spec / exact values:**
  - `UpdateNotebookChatSessionRequest` currently = `{ title?; model_override?: string | null }`. Add
    `parent_session_id?: string | null` (and `quote?: string | null`). Backend `update_session`
    already handles both via `exclude_unset` (`api/routers/chat.py` L486–490), and `parent_session_id`
    /`quote` are in `ChatSession.nullable_fields`, so PUT-ing `null` clears them.
  - New i18n keys (add to `chat`): `sidebarTitle` ("Chats"), `searchChats` ("Search chats…"),
    `hideChat` ("Hide"), `deleteChat` ("Delete chat"), `deleteChatConfirm` ("Delete this chat
    permanently? This cannot be undone."), `promoteToMain` ("Make a main chat"), `sideChats` ("Side
    chats"), `sideChatsCount` ("Side chats ({count})"), `noChats` ("No chats yet"), `renameChat`
    ("Rename").
- **Reuse:** `chatApi.updateSession` (already forwards an arbitrary `UpdateNotebookChatSessionRequest`
  body — verify in `frontend/src/lib/api/chat.ts`), the silent-update pattern from `renameSession`.
- **Steps:**
  1. Extend `UpdateNotebookChatSessionRequest` in `api.ts` with `parent_session_id?: string | null`
     and `quote?: string | null`.
  2. Verify `chatApi.updateSession(sessionId, data)` passes the body through unchanged; if it whitelists
     fields, add the two.
  3. In `useNotebookChat.ts`, add a silent `promoteToMain(sessionId)` (mirrors `renameSession`: call
     `chatApi.updateSession(sessionId, { parent_session_id: null, quote: null })`, then invalidate
     `QUERY_KEYS.notebookChatSessions(notebookId)` + `QUERY_KEYS.notebookChatSession(sessionId)`).
     Export it from the hook's return object.
  4. Add derived selectors to the hook return: `mainSessions` = `sessions.filter(s => !s.parent_session_id)`
     and a `sideSessionsOf = (parentId) => sessions.filter(s => s.parent_session_id === parentId)`
     (memoized).
  5. Add the i18n keys.
- **Verify:** `cd frontend && npm run typecheck` (or `npx tsc --noEmit`) and `npm run lint` pass. No
  visual change in the running app.

### Chunk 2 — ChatSidebar + explicit-open visibility model  *(the core; largest chunk — may split 2a/2b)*
- **Goal:** Replace the dock tab strip with a sidebar that lists MAIN chats; rework the workspace store
  so chats are **explicitly opened** instead of every session auto-becoming a docked tab. After this
  chunk: the dock card shows a left **sidebar rail** (main chats, search, click-to-open, +new) and the
  active opened main chat's conversation on the right; popped multi-panels still work.
- **Read first:** `frontend/src/lib/stores/chat-workspace-store.ts` (whole), `ChatDock.tsx` (whole —
  esp. tab strip L176–229 & `dockedSessions`/`activeDockedId` L94–118), `notebooks/[id]/page.tsx`
  (`renderCard` L351–445, store wiring L88–94), `frontend/src/components/notebooks/ChatColumn.tsx`.
- **Spec / exact values:**
  - **Sidebar = main chats only:** drive from `chat.mainSessions` (Chunk 1). Recency order — `sessions`
    already arrive sorted by the API (`updated`/`created` desc; confirm in `get_sessions`).
  - **Visibility model:** today `syncChats` creates a `WorkspaceChat` for *every* session, all
    `docked: true`, so all mains render as tabs (`ChatDock` L94–101). New model: a chat is either
    **open** (rendered — docked in the dock or popped in the track) or **closed** (listed in the
    sidebar only). Add to the store: an `openIds: string[]` (or `open: boolean` on `WorkspaceChat`)
    and actions `openChat(id)` / `closeChat(id)`. `syncChats` must NOT auto-open every session — it
    reconciles known entries and, when nothing is open, opens the most-recent main (or none).
  - **Active main:** keep `activeChatId`; opening a main from the sidebar sets it active and docks it.
- **Reuse:** existing `setDocked`/`removeChat`/`order`/`panelOrder` machinery; `ChatPanel` (dock body);
  `deriveChatTitle`; the multiplexed hook (`getMessages`/`sendMessageTo`/`switchSession`).
- **Steps:**
  1. **Store:** introduce the open/closed concept (prefer `open: boolean` on `WorkspaceChat`, default
     `false`). Rewrite `syncChats` so it (a) keeps existing entries' state, (b) creates closed entries
     for new sessions instead of auto-docked ones, (c) on first load with no open chat, opens the
     most-recent main. Add `openChat(id)` (sets `open: true`, `docked: true`, active) and `closeChat(id)`
     (sets `open: false`; if it was a popped panel, also drop its panel token). Keep sub-chat hydration
     but gated on `open` (Chunk 4 refines).
  2. **New `ChatSidebar.tsx`** (`frontend/src/components/notebooks/`): props `{ notebookId, chat, ... }`.
     Renders a header (`t('chat.sidebarTitle')` + `+` → `chat.createSession`), a search input filtering
     by title, and a scrollable list of `chat.mainSessions`. Each row: title (click → `openChat` +
     `switchSession`), active highlight, a `⋯`/inline rename, and a trash icon (Chunk 3 wires delete).
     Empty state `t('chat.noChats')`.
  3. **ChatDock:** remove the tab strip (`SortableTab`, `tabItemIds`, the `SortableContext` block). Keep
     the model picker + context meter + side-chat default cog. Render `ChatSidebar` as a **left rail**
     inside the dock card (flex row: sidebar ~`w-56` + the active `ChatPanel`). The active conversation
     = `chat.getMessages(activeMainId)`. `+` and switching now flow through the sidebar/`openChat`.
  4. **page.tsx:** no new track panel needed (sidebar lives inside the `dock` card). Confirm
     `renderCard('dock')` still renders `ChatColumn`/`ChatDock`. Popped panels (`renderCard` else-branch)
     unchanged.
  5. i18n: use keys from Chunk 1.
- **Verify:** typecheck + lint pass. Manually (or by reasoning) confirm: sidebar lists mains, clicking
  opens it in the dock, `+` creates a chat, popped panels still render, no orphaned tab-strip code.
- **If too big:** split — **2a** = store visibility model + `ChatSidebar` scaffold (rendered but dock
  still tabbed); **2b** = remove tab strip & wire dock to the sidebar.

### Chunk 3 — Hide vs Trash (X = hide, 🗑 = delete)
- **Goal:** Make X non-destructive (hide) everywhere, and add an explicit trash (delete) control. Safe
  now because Chunk 2's sidebar can reopen a hidden chat.
- **Read first:** `ChatDock.tsx` (after Chunk 2), `PoppedChatPanel.tsx` (header L64–87, `onClose`),
  `notebooks/[id]/page.tsx` (L434–443 `onClose={() => chat.deleteSession(token)}`), `ChatSidebar.tsx`.
- **Spec / exact values:**
  - **X (hide):** wire to `closeChat(id)` (store) — NOT `deleteSession`. Today `PoppedChatPanel`'s X and
    the page wire to `chat.deleteSession` (page L441) — change to hide.
  - **Trash (delete):** new icon (`Trash2`) that calls `chat.deleteSession(id)`, guarded by a confirm
    (`t('chat.deleteChatConfirm')`). Lives in: the sidebar row (for main chats) and the side-chats
    control / popped panel header (for side chats).
  - Drop the old `canClose`/"keep at least one chat" constraint where it only existed to prevent
    deleting the last tab — hiding the last chat is fine (sidebar still lists it). Keep a guard on
    *delete* if desired, but not required.
- **Reuse:** `deleteSession` mutation (already invalidates + toasts), a confirm dialog primitive from
  `components/ui` (check for an existing `AlertDialog`).
- **Steps:** repoint all X handlers → `closeChat`; add trash buttons → `deleteSession` (+ confirm);
  update tooltips/labels to the new i18n keys.
- **Verify:** typecheck/lint. Hiding a chat removes its panel but keeps it in the sidebar; trashing
  removes it from the DB (session list refetch drops it).

### Chunk 4 — Side-chat scoping + "side chats" control
- **Goal:** Side chats appear ONLY under the active main chat, and each open main exposes a "side chats
  (n)" control listing all its side chats (including hidden) so they can be reopened. Side chats never
  show in the sidebar (already true — sidebar lists `mainSessions`).
- **Read first:** `chat-workspace-store.ts` `syncChats` sub-chat hydration (L83–91), `page.tsx`
  `displayOrder`/nesting (L185–214), `PoppedChatPanel.tsx`, `useNotebookChat.ts` `sideSessionsOf`.
- **Spec / exact values:**
  - Stop force-hydrating every persisted sub-chat as an always-open popped panel. A side chat is open
    only if explicitly opened (or freshly created). The page's `displayOrder` already nests popped
    sub-chats under their parent — keep that for *open* side chats.
  - **"Side chats (n)" control:** rendered in the active main's dock header (and/or each open main
    panel). Uses `chat.sideSessionsOf(mainId)`; a dropdown/popover lists them (title), click →
    `openChat(id)` (pops it out as a panel anchored to the parent). Count includes hidden ones.
- **Reuse:** `createSubChat`/`createSidePanel` (unchanged), `setDocked(false)` to pop, the existing
  nesting in `displayOrder`, a `DropdownMenu` from `components/ui` (as `SideChatDefaultMenu` does).
- **Steps:** gate sub-chat hydration on open-state in `syncChats`; build the side-chats dropdown
  component; wire it into the dock header for the active main; ensure opening a side chat pops it.
- **Verify:** typecheck/lint. Switching the active main swaps which side chats are reachable; hidden
  side chats reappear via the control; sidebar still shows only mains.

### Chunk 5 — Promote ("collapse") side chat → main
- **Goal:** A control on a side-chat panel that promotes it to a main chat (clears `parent_session_id`);
  it then appears in the sidebar and is no longer scoped to a parent.
- **Read first:** `PoppedChatPanel.tsx` header, `useNotebookChat.ts` `promoteToMain` (Chunk 1),
  `ChatSidebar.tsx`.
- **Spec / exact values:** button in the popped panel header (only shown when the session has a
  `parent_session_id`), `t('chat.promoteToMain')`, calls `chat.promoteToMain(session.id)`. The session
  list refetch makes it a main; remove the "discussing this passage" banner once promoted (banner is
  driven by `quote`, which `promoteToMain` clears).
- **Reuse:** `promoteToMain` (Chunk 1).
- **Steps:** add the button + handler; confirm the store reconciles it from sub-chat → main on refetch
  (it should appear in the sidebar and drop out of the parent's side-chats list).
- **Verify:** typecheck/lint. Promote a side chat → it shows in the sidebar, banner gone, no longer in
  the parent's "side chats" list.

### Deferred (documented, not built now)
- **Sidebar polish** ⊘ — drag-reorder within the sidebar, inline rename affordance refinements,
  grouped/foldered sections (Decision 1 deferred grouping).
- **Hide-state persistence** ⊘ — persist `open/closed` (and which main is active) across reloads by
  adding `persist`/`partialize` to `chat-workspace-store` (see Q-hide-persistence). Default v1 is
  ephemeral.
- **Auto-name from first message** ⊘ — already implemented (`deriveChatTitle` + `renameSession` on
  first send in `ChatDock.handleSend`/`PoppedChatPanel.handleSend`); just verify it still fires after
  the Chunk 2 rewrite; no new work expected.

## Verification (end-to-end)
- `cd frontend && npm run typecheck && npm run lint` (or `npx tsc --noEmit`). Fix new errors only;
  ignore pre-existing baseline noise.
- Run the app (`on-frontend` systemd --user unit is already running — restart it to pick up changes;
  do NOT launch a second dev server). Open a notebook with several chats and confirm: sidebar lists
  main chats; click opens one in the dock; `+` creates a chat; X hides (chat stays in sidebar); trash
  deletes; a side chat appears under its active main via the "side chats" control; promote moves a side
  chat into the sidebar; popped multi-panels still work side-by-side.
- No backend changes expected; if `api`/`worker` units are touched, restart them too.

## Open Questions (surface to human; don't guess)
- **Q-hide-persistence** — Should hide/open state survive a reload? The workspace store is currently
  ephemeral (re-syncs each mount). **Default (v1): frontend-only/ephemeral** — on reload, open the
  most-recent main, everything else closed. Persisting needs `persist`+`partialize` on the store
  (deferred). Confirm the ephemeral default is acceptable.
- **Q-sidebar-placement** — Sidebar as a **left rail inside the dock card** (default, P-sidebar-placement)
  vs a dedicated fixed panel in `PanelTrack`. Default chosen to avoid touching track/displayOrder code;
  revisit if the dock feels cramped.

## Reference index
- **Files touched:**
  - `frontend/src/lib/types/api.ts` (Chunk 1)
  - `frontend/src/lib/api/chat.ts` (Chunk 1 — verify passthrough)
  - `frontend/src/lib/hooks/useNotebookChat.ts` (Chunks 1, 4, 5)
  - `frontend/src/lib/stores/chat-workspace-store.ts` (Chunks 2, 3, 4)
  - `frontend/src/components/notebooks/ChatSidebar.tsx` (NEW — Chunk 2; trash in 3)
  - `frontend/src/components/notebooks/ChatDock.tsx` (Chunks 2, 3, 4)
  - `frontend/src/components/notebooks/PoppedChatPanel.tsx` (Chunks 3, 4, 5)
  - `frontend/src/app/(dashboard)/notebooks/[id]/page.tsx` (Chunks 2, 3)
  - `frontend/src/lib/locales/en-US/index.ts` (Chunk 1; add keys as later chunks need)
- **Primitives to reuse:** `useNotebookChat` (sessions, createSession, createSubChat, createSidePanel,
  updateSession, deleteSession, renameSession, switchSession, getMessages, getIsSending, sendMessageTo,
  setSessionModelOverride); `ChatPanel` (dock body); `deriveChatTitle`; `useChatWorkspaceStore`;
  `ChatModelPicker`; `SideChatDefaultMenu`; `components/ui` DropdownMenu/AlertDialog.
- **Deps available:** `@dnd-kit/*` (page-level DndContext), `@tanstack/react-query`, `zustand`,
  `sonner`, `lucide-react`.

### Post-exploration refinements (confirmed APIs)
- **Backend `PUT /chat/sessions/{id}`** (`api/routers/chat.py` L464–525) uses `request.model_dump(
  exclude_unset=True)` and explicitly applies `title`, `model_override`, `parent_session_id`, `quote`
  when present → sending `parent_session_id: null` **clears** it (promote works with zero backend
  changes). `ChatSession.nullable_fields = {model_override, parent_session_id, quote}` allows null saves.
- **`get_sessions`** returns sessions via `notebook.get_chat_sessions()` ordered `updated desc`, each
  with `parent_session_id`/`quote`/`model_override` — so `mainSessions`/`sideSessionsOf` filtering works
  on the existing list with no new endpoint.
- **Current visibility behavior to change:** `chat-workspace-store.syncChats` creates a `WorkspaceChat`
  for every session (`createChat` → `docked: true`), and `ChatDock` renders all docked sessions as
  tabs. This is the exact behavior Chunk 2 replaces with explicit open/closed.
- **X today = delete:** `ChatDock` `SortableTab onClose → chat.deleteSession` (L195) and `page.tsx`
  popped `onClose → chat.deleteSession` (L441). Chunk 3 repoints these to hide.
- **`UpdateNotebookChatSessionRequest`** (api.ts L279) currently lacks `parent_session_id`/`quote`;
  Chunk 1 adds them. `CreateNotebookChatSessionRequest` already has both.
- **i18n:** existing `chat` keys live in `frontend/src/lib/locales/en-US/index.ts` (e.g. `newChat`,
  `closeChat`, `dockBack`, `discussingPassage`).
