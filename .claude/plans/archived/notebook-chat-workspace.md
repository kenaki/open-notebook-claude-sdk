# Notebook Multi-Chat Workspace — COORDINATOR / INDEX

> **This file is the shared source of truth, not an executable plan.** It was split (2026-06-22) from
> one 13-chunk master into **5 parallel plan files** so separate Claude Code chats can each own one
> plan. A chat picks **one plan file**, reads **this coordinator first** for shared law, then executes.
> **Do not implement chunks from this file** — implement from the plan files listed below.
>
> **Input artifact:** `design_handoff_notebook_chat/` (README.md + `Open Notebook.dc.html` prototype).
> The README's **Design Tokens** and behavior spec are law; the `.dc.html`/`support.js` runtime is
> **reference only — do not port it.** Re-express in React/Tailwind.
> **Coordinate with:** `.claude/plans/pdf-viewer-citations.md` (still active; shares citation files +
> migration numbering — see Reconciliation).

---

## The 5 plans (pick ONE per chat)

| Plan file | Chunks | Track | Starts when | Concurrent with |
|---|---|---|---|---|
| `ncw-a-theme-shell.md` | 0, 1 | Theme + app shell (frontend-only) | **immediately** | **B** |
| `ncw-b-backend-chat.md` | 2, 3, 4, 5 | Backend chat extensions | **immediately** | **A** |
| `ncw-c-workspace-layout.md` | 6, 7, 8 | Panel-track layout + dock | after **A** Chunk 0 lands | — |
| `ncw-d-feature-surfaces.md` | 9, 10, 11, 12 | Citations / tool-use / sub-chats / media UI | after **B** and **C** land | — |
| `ncw-e-polish.md` | 13 | Polish / animations / mobile / i18n sweep | after **D** lands | — |

**Parallel waves (same working tree, sequential landing):**
```
Wave 1:  A  ‖  B        (run concurrently — they share ZERO files)
Wave 2:  C              (needs A's Chunk 0 token swap)
Wave 3:  D              (needs B's backend fields + C's dock/ChatPanel)
Wave 4:  E              (needs D)
```
The DAG genuinely allows only **two** truly-parallel streams at the start (A and B). C/D/E are a
sequential chain because they progressively extend the same frontend chat files.

### Cross-plan status (single source of truth — each plan also keeps its own per-chunk table)
| Plan | Status | Owner / session | Landed on branch |
|---|---|---|---|
| A — theme-shell (0,1) | ☑ done | | claude-agent-integration (Chunks 0+1 landed) |
| B — backend-chat (2,3,4,5) | ☑ done | kenaki | claude-agent-integration (Chunks 2+3+4+5 all landed) |
| C — workspace-layout (6,7,8) | ☑ done | kenaki | claude-agent-integration (Chunks 6+7+8 all landed) |
| D — feature-surfaces (9,10,11,12) | ☑ done | kenaki | claude-agent-integration (Chunks 9+10+11+12 all landed) |
| E — polish (13) | ☑ done | kenaki | claude-agent-integration (Chunk 13 landed) |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked. **When a plan finishes, update this row AND the
Changelog below**, so other chats see what landed.

### Shared-file ownership (same-tree, sequential landing — READ BEFORE EDITING A SHARED FILE)
The hybrid grouping was chosen so concurrent plans don't share files. The table records the few files
touched by **more than one plan** and who edits them in what order. If you're editing a file listed
here, confirm the prior owner has **☑ landed** (see Cross-plan status) before you start.

| File | Plans that touch it | Order / rule |
|---|---|---|
| `api/routers/chat.py` | **B only** | B owns it fully (chunks 2–5 are all in B). No cross-plan conflict. |
| `open_notebook/graphs/chat.py` | **B only** | B owns it fully. |
| `open_notebook/ai/claude_agent.py` | **B only** | B owns it fully. |
| `prompts/chat/system.jinja` | **B** (+ pdf-plan) | B edits; coordinate the page-anchor merge with `pdf-viewer-citations.md`. |
| `components/source/ChatPanel.tsx` | **C** then **D** then **E** | C restructures (dock); D extends (cards/tooluse/subchat/media); E polishes. Sequential by dependency — safe. |
| `lib/types/api.ts` | **C** then **D** | C adds chat-workspace types; D adds Citation/tool/media TS shapes. C lands first. |
| `lib/hooks/useNotebookChat.ts` | **C** then **D** | C wires dock send; D adds citations/subchat/media. C lands first. |
| `app/(dashboard)/notebooks/[id]/page.tsx` | **C** then **E** | C builds the track; E adds mobile. C lands first. |
| `frontend/src/app/globals.css` | **A** then **E** | A swaps tokens; E adds keyframes. A lands first. |
| `lib/locales/*` (**14 locales**) | **A, D, E** | **Append-only** translation keys — never delete another plan's keys. E does the final sweep. |
| migrations / `async_migrate.py` | **B** (+ pdf-plan) | B claims the next free migration number; re-check vs pdf-plan (see Reconciliation). |

### Changelog (cross-plan — append one line when a plan lands)
- 2026-06-22: Split the 13-chunk master into 5 parallel plans (A–E) + this coordinator.
- 2026-06-22: Plan A Chunk 0 landed — `globals.css` token swap to handoff warm-paper/indigo palette
- 2026-06-22: Plan B Chunk 2 landed — sub-chat fields (`parent_session_id`+`quote`) on `ChatSession` + nullable; **migration 16 claimed/applied** (`16.surrealql`+down, registered in `async_migrate.py`; DB now @16, single row); threaded through `Create/Update SessionRequest`, `ChatSessionResponse`, all session endpoints (`getattr`); `quote` added to `ThreadState` + injected in `execute_chat`; `system.jinja` SEED PASSAGE block (conditional). Live-verified POST/GET round-trip. **Note for pdf-plan: 16 is now taken → pdf-plan takes 17.**
- 2026-06-22: Plan B Chunk 3 landed — structured citations. New `Citation{id,type,number,title,snippet,page}` model + `citations[]`/`followups[]` on `ChatMessage` (`api/routers/chat.py`). `_resolve_citations()` helper: regex `(source_insight|note|source):id` **tolerating optional `#p=<n>`** (pdf-plan hook → `Citation.page`), dedup + first-appearance numbering (ports `source-references.tsx` logic to backend), async title/snippet fetch via `Source`/`Note`/`SourceInsight.get`, splits off the `---FOLLOWUPS---` block (markers KEPT inline for back-compat). `_build_chat_message()` shared by `execute_chat` + `get_session` (human msgs → empty arrays). `system.jinja` gains a conditional **FOLLOW-UP SUGGESTIONS** block emitting `---FOLLOWUPS---` + 2–3 questions. **Shapes are frozen for Plan D's TS mirror** (`Citation`). Live-verified end-to-end on "Greek learning" notebook: AI message returned a real citation (title `Modern Greek Grammar Notes.pdf` + snippet), 3 followups, sentinel stripped from `content`, inline marker retained, GET persists the shape. **system.jinja now holds BOTH the SEED PASSAGE (chunk 2) and FOLLOW-UP blocks — pdf-plan must merge its page-anchor instruction with both.**
- 2026-06-22: **Plan B Chunk 4 landed** — tool-use disclosure capture. `claude_agent.py` `_run` now returns `(text, tool_uses)`: collects `ToolUseBlock`s from each `AssistantMessage` (keyed by id) and matches `ToolResultBlock`s (delivered on the synthetic `UserMessage` the SDK emits after each tool) back by `tool_use_id`; `_stringify_tool_result()` flattens the SDK's `str | list[dict] | None` content. `generate_with_claude_agent` returns `AIMessage(content, additional_kwargs={"tool_uses": [...]})` — rides the message object through LangGraph + survives `model_copy`/SqliteSaver checkpoint. New `ToolUseDisclosure{id,tool_name,tool_input,tool_result,is_error}` model in `api/routers/chat.py` + `tool_uses: Optional[List[ToolUseDisclosure]] = None` on `ChatMessage`, populated in `_build_chat_message()` from `additional_kwargs.get("tool_uses")` (empty/absent → None). **Raw** MCP tool names sent (Q-toolnames default — UI maps). **Shape frozen for Plan D's TS mirror.** Live-verified on "Greek learning": agent-routed chat (`claude_agent::` override) → `tool_uses[]` = 5 entries incl. `mcp__open_notebook__search`×2 + `mcp__open_notebook__get_source` (inputs + results captured), GET persists the exact shape; Ollama qwen3.6 Esperanto chat → `tool_uses=None`, HTTP 200, no crash. test_claude_agent 16 pass (5 new), test_domain 23 pass (same 8 pre-existing credential failures, unrelated). **Plan B Chunk 5 (media) remains.**
  (light + dark, exact hex), new handoff-only tokens (`--panel-2`/`--text-3`/`--border-2`/`--accent-soft`
  /`--accent-soft-2`/`--ready`/`--processing`/`--failed`/`--shadow`) exposed via `@theme inline` as
  `--color-*` utilities, `--radius:0.75rem`, Inter wired through `--font-sans` (`layout.tsx` exposes
  `--font-inter`). `npm run build` green. **Plan C may start** once it confirms this (Chunk 0 token swap).
  Plan A Chunk 1 (app-shell reskin) still TODO.
- 2026-06-22: **Plan A COMPLETE** (Chunk 1 landed). `AppSidebar.tsx` reskinned to the handoff: width
  236px (collapsed w-16 unchanged), nav regrouped into **WORKSPACE** (Sources, Notebooks, Ask & Search,
  Podcasts) + **SYSTEM** (Models, Transformations, Settings, Advanced — Q-nav default applied), section
  eyebrows 10.5px/600/.07em in `text-text-3`, active nav = `bg-card` + `shadow-[var(--shadow)]` +
  `text-foreground` with `text-primary` icon (inactive `text-muted-foreground`/`text-text-3`), inter-group
  Separator removed for handoff spacing. `navigation.workspace`/`navigation.system` keys **appended** to
  all 14 locales (old collect/process/create/manage keys kept — append-only). `npm run build` green,
  AppSidebar test (3) + eslint pass. **Page header (title·badge·counts·toggle) deferred to Plan C** —
  it belongs in `notebooks/[id]/page.tsx` (C/E own it), not in the all-pages `AppShell`. Plans C, D, E
  may now proceed in DAG order.

---

- 2026-06-22: **Plan C Chunk 6 landed** (panel-track layout engine). Notebook desktop view is now a
  horizontal `overflow-x:auto` **PanelTrack** of resizable `PanelCard`s (Sources 296 / Notes 316 / Dock
  520 default px; drag right edge to resize, clamped **240–980**; **double-click** a card to
  maximize/restore — focused panel `flex:1`, siblings hidden). New
  `components/notebooks/{PanelTrack,PanelCard}.tsx`; `notebook-columns-store` extended with
  `widths`/`maximized`/`setWidth`/`toggleMaximized` (persist key unchanged). `SourcesColumn`/
  `NotesColumn`/`ChatColumn` are **unchanged** (wrapped, not refactored) → mobile tab path untouched;
  minimize-to-chip reuses the existing `CollapsibleColumn` collapse. **Dep note:** skipped
  `react-resizable-panels` (its proportional fill model conflicts with independent-px panels in a
  scrolling track) → custom pointer-resize handle, **no new dep**. Chunk 8 still plans `@dnd-kit/core`.
  `npm run build` green, eslint clean, ChatColumn test 2/2. **Chunks 7,8 remain in Plan C.**

- 2026-06-22: **Plan C Chunk 7 landed** (multi-chat store + dock tabs + composer + in-dock model picker).
  New `lib/stores/chat-workspace-store.ts` (ephemeral client layer over sessions — `chats{}`/`order`/
  `activeChatId` + `syncChats`/`setActiveChat`/`setDraft`/`removeChat` + Chunk-8 stubs; `WorkspaceChat`/
  `ChatPendingMedia` types in `lib/types/api.ts`, **frozen base for Plan D**). New
  `components/notebooks/ChatDock.tsx`: dock panel shell + **dock-header global model picker** (bound to
  `useClaudeAgentModel`/`useUpdateClaudeAgentModel`, Decision 8 — writes the global `claude_agent` config,
  reflected in Settings) + **context-meter pill** + **tab strip** (one tab/session, **close enforces ≥1**,
  pop-out disabled until Chunk 8, **"+"** new chat). `ChatColumn` now renders `<ChatDock>` (owns the hook +
  stats). **Shared files (stable for Plan D):** `ChatPanel.tsx` re-skinned with an additive
  `variant:'standalone'|'dock'` (**source chat unchanged**) — bubbles (`14px 14px 4px 14px`), auto-grow
  composer (cap 140, ⌘↵), sparkle empty-state + 3 suggestions, controlled-draft props; `useNotebookChat`
  gained a silent `renameSession` (auto-title from first message). i18n **append-only across all 14
  locales** (`chat.{newChat,popOut,closeChat,emptyTitle,emptyHelper,suggestion*×3,meter*×3}`); removed the
  orphaned `chat.chatWithNotebook` (kept locales in parity). `npm run build` green, eslint clean,
  ChatColumn test 2/2, i18n parity ✓ (pre-existing unused-key debt `navigation.collect`/`manage` is
  **Plan A's**, left untouched). **Chunk 8 remains in Plan C; Plan D's dock/ChatPanel base is ready.**

- 2026-06-22: **Plan B COMPLETE** (Chunk 5 landed — media attachments). Upload helpers factored out of
  `sources.py` into **`api/upload_utils.py`** (`generate_unique_filename`, `save_uploaded_file(upload_file,
  upload_folder=UPLOADS_FOLDER)`, `resolve_within(folder, filename)` path-traversal guard); `sources.py`
  now imports them (the `test_sources_api` patch target `api.routers.sources.save_uploaded_file` still
  resolves — re-exported into the module namespace). New `CHAT_MEDIA_FOLDER=./data/uploads/chat-media/`
  in `config.py` (files only, no DB record — Q-mediastore default). New **`MediaItem{type:Literal["image",
  "video"]; url; label; duration:Optional[str]}`** in `api/routers/chat.py` — **shape frozen for Plan D's
  TS mirror**; `media: List[MediaItem]=[]` added to `ExecuteChatRequest` **and** `ChatMessage`. New
  **`POST /chat/media`** (multipart; classifies image/* vs video/* by content-type, 400 otherwise; saves
  via shared helper; returns MediaItem with `url=/api/chat/media/<file>`) + guarded **`GET /chat/media/{
  filename}`** (FileResponse; `resolve_within` → 403 on traversal, 404 if absent). `execute_chat` rides
  `media` on the user `HumanMessage.additional_kwargs` (round-trips through the SqliteSaver checkpoint);
  `_build_chat_message()` surfaces it (AI msgs → `[]`). **Esperanto/LangChain (vision) path:**
  `graphs/chat.py` `_attach_media_blocks()` rebuilds HumanMessages with media into multimodal
  `content=[{text},{image_url:data-uri},…]` (images inlined as base64 `data:` URIs via `_media_to_data_uri`,
  videos→text refs); applied **only at `model.invoke()`** so `provision_langchain_model` still token-counts
  the original text payload (no large-context false-trigger). **Agent path (Decision 9 / Q-agentmedia):**
  `claude_agent.py` `_flatten` appends `[Attached media — <type>: <label> (<url>)]` file references, NOT
  inlined images. **Live-verified on "Greek learning":** `POST /chat/media` (png) → fetchable (200, bytes
  match), traversal-safe; agent-path `execute` with `media[]` → HTTP 200, AI acknowledged "the attachment
  reference for red.png", `media[]` round-trips on the human turn via `GET` (AI msg → `[]`); Esperanto path
  **built + sent** the `image_url` block to Ollama qwen3.6 → provider 400 "Failed to load image" = **qwen3.6
  is not vision-capable** → payload-build verified, **model-side image test BLOCKED on a vision model** (no
  local vision LM exists; not faked). `_attach_media_blocks` unit-checked (data-URI image block + video text
  ref + non-media passthrough). test_domain + test_claude_agent + test_sources_api **53 pass**. **Plan D's
  backend dependency (`MediaItem`/`Citation`/`ToolUseDisclosure` shapes) is now fully satisfied — but D
  still also waits on Plan C (Chunk 8 remains).**
- 2026-06-22: **Plan C COMPLETE** (Chunk 8 landed — pop-out / dock-back / drag-reorder / maximize /
  nesting). **Decisions (human):** multiplex ONE chat hook (not one-per-chat) + add `@dnd-kit`
  (`core`+`sortable`+`utilities`). **`useNotebookChat` multiplexed & lifted to `page.tsx`** (one instance
  shared by the dock + every popped panel): `useQueries` over visible sessions, per-session optimistic
  `setQueryData`, new `getMessages`/`getIsSending`/`sendMessageTo`; back-compat fields delegate to the
  active session. **Stores:** `notebook-columns-store.maximized` widened `PanelId|null → string|null` (can
  name a popped chat); `chat-workspace-store` gained `panelOrder` anchor list (+ `FIXED_PANEL_IDS` export,
  `reorderPanels`) maintained on pop/dock — still ephemeral. **`PanelCard` now sortable** (left-edge grip;
  self-hide removed, page controls visibility). **New `PoppedChatPanel`** (reuses `ChatPanel` dock variant,
  `composerMaxHeight=120`, dock-back/close header, "DISCUSSING THIS PASSAGE" banner when `quote`).
  **`ChatDock`** takes the `chat` hook, shows docked-only sortable tabs, **pop-out enabled** (↗ +
  drag-to-drop-zone), exports `TAB_DND_PREFIX`, `enablePopOut=false` on mobile. **Page** wraps both layout
  branches in one `DndContext`, computes the handoff **derived display-order** (anchors + recursive
  `childChatsOf` + orphan promotion) and renders cards in that DOM order in a `SortableContext`; maximize
  focus-set + stale-clear; `PopZone` dashed droppable. **`parentId`/`quote` are null until Plan D** — the
  nesting/banner/passage-empty-state are built so D's sub-chats slot in right of their parent for free.
  **Deviations (documented):** reorder via a dedicated left-edge grip (handoff said "drag header"; headers
  are heterogeneous); mobile pop-out hidden (Plan E owns mobile). i18n **append-only ×14**
  (`chat.{dockBack,dropToPopOut,passageEmptyTitle,passageEmptyHelper}`). `ChatColumn` is now presentational
  (receives the hook). `npm run build` green, eslint clean, ChatColumn 2/2, i18n parity ✓ (pre-existing
  unused-key debt `navigation.collect/manage` is Plan A's, untouched). **Plan D is now UNBLOCKED — both
  deps satisfied (Plan B backend shapes ☑ + Plan C dock/ChatPanel/useNotebookChat/page ☑).**

- 2026-06-22: **Plan D Chunk 9 landed** (structured citations UI). TS `Citation` mirror added to
  `lib/types/api.ts` (`{id,type,number,title?,snippet?,page?}` — `id` is the **full prefixed record id**)
  + optional `citations?`/`followups?` on **both** `SourceChatMessage` and `NotebookChatMessage` (the dock
  feeds `NotebookChatMessage[]` into `ChatPanel`'s `SourceChatMessage[]` prop, so both must carry them).
  New `components/source/MessageReferences.tsx`: `MessageReferences` (numbered cards — number badge +
  type icon + title/id + snippet, click strips the `type:` prefix → existing `handleReferenceClick`→
  `openModal`; carries `data-citation-*` for **Plan E's source-card flash**) + `FollowupChips` (pill row,
  click → sends the question). `ChatPanel` AI render now shows cards when `message.citations?.length` and
  chips when `followups?.length`, and passes `appendReferenceList={!citations?.length}` into
  `AIMessageContent`. `convertReferencesToCompactMarkdown` gained an additive 3rd param
  `appendReferenceList=true` (`source-references.tsx`, shared w/ pdf-plan) — when false it does the inline
  `[n]` rewrite but **skips the appended "References:" list**, so cards don't duplicate it; **old sessions
  (no `citations` array) fall back to the inline appended list unchanged**. `useNotebookChat` needed **no
  change** — server messages flow through verbatim, the new fields ride along once typed. i18n
  **append-only ×14**: one new key `chat.suggestedFollowups` (`common.references` already existed). `npm run
  build` green, eslint clean on touched files, ChatColumn 2/2, i18n parity ✓ (14/14). **Chunks 10/11/12
  remain in Plan D** — each scoped to its own message fields (`tool_uses`/sub-chat/`media`), untouched here.

- 2026-06-22: **Plan D Chunk 10 landed** (tool-use disclosure UI). TS `ToolUseDisclosure` mirror added to
  `lib/types/api.ts` (`{id,tool_name,tool_input:Record<string,unknown>,tool_result?,is_error?}` — exact
  backend mirror) + optional `tool_uses?` on **both** `SourceChatMessage` and `NotebookChatMessage` (same
  reason as Chunk 9: the dock feeds `NotebookChatMessage[]` into `ChatPanel`'s `SourceChatMessage[]` prop).
  New `components/source/ToolUseDisclosure.tsx`: a `ui/collapsible` whose trigger is the summary line
  (headline = the first `search` tool's label, else the first call's label; `· N` count; chevron
  **rotates 90° over .18s** via `group-data-[state=open]`), expanding to one row per MCP call — friendly
  label (raw-name→label map: `…search`→"Searched your sources", `…source(s)`→"Read source(s)",
  `…note`→"Read note", `…notebook(s)`→"Read notebook", default→"Used a tool") + a monospace detail pulled
  from `tool_input` (query → id → first string) + destructive tint when `is_error`. Wired into `ChatPanel`
  AI render **above the answer bubble** (handoff "Other chat UI" order: tool-use → answer → media →
  citations), gated `message.type==='ai' && message.tool_uses?.length` → renders **nothing** on the
  Esperanto path / old sessions (`tool_uses` is null there). `useNotebookChat` needed **no change** (fields
  ride along once typed). i18n **append-only ×14**: `chat.{searchedYourSources,readSources,readNote,
  readNotebook,usedTool}`. `npm run build` green, eslint clean on touched files (exit 0), ChatColumn 2/2,
  i18n parity ✓ (14/14). **Chunks 11/12 remain in Plan D** — sub-chats (`parent_session_id`/`quote`) +
  media (`media[]`), each untouched here.

- 2026-06-22: **Plan D Chunk 11 landed** (sub-chats — selection → "Chat about this" → anchored panel).
  `parent_session_id?`/`quote?` added to `BaseChatSession` (flows to `NotebookChatSession`, reload
  hydration) + `CreateNotebookChatSessionRequest` (`lib/types/api.ts`). New `useNotebookChat.createSubChat
  (parentId, quote, title?)`: POSTs `createSession({parent_session_id, quote, title=trunc(quote,26)+"…"})`,
  invalidates the session list, returns the new session (toast+null on error). **Found & closed a real gap:**
  Chunk 8's `syncChats(ids)` nulled `parentId/quote/docked`, so sub-chats did **not** survive a reload.
  `syncChats` now takes session objects (`SyncChatSession[]`) and **hydrates** any session with a
  `parent_session_id` as a popped panel (`docked:false`+`parentId`+`quote`) + appends it to `panelOrder` —
  the page's existing display-order algo then nests/promotes it. ChatDock call site updated accordingly.
  New `components/notebooks/PassageSelectionMenu.tsx`: one document-level `mouseup` watcher (mounted once on
  the desktop track) → reads `window.getSelection()` (≥2 chars), walks `range.commonAncestorContainer` →
  `.closest('[data-chat-scope]')` for the parent chat id, renders a `position:fixed` accent pill ("Chat about
  this" + sparkle) **portaled to body** at `top=selTop−46`, centered; dismiss on outside-mousedown / capture-
  scroll / empty selection; click → spawn + clear selection. `ChatPanel` gains **two minimal props** (kept
  small for Chunk 12): `chatScopeId` (stamps `data-chat-scope={id}` on **AI** message bodies only) +
  `autoFocus` (mount-only composer focus). `ChatDock` passes `chatScopeId={activeDockedId}`; `PoppedChatPanel`
  passes `chatScopeId={session.id}`, forwards `autoFocus`, and its quote banner now shows the **"DISCUSSING
  THIS PASSAGE"** eyebrow (Chunk 8 had built the container w/o the label). Page mounts the menu (desktop only —
  sub-chats are popped panels), wires `handleCreateSubChat`→`pendingFocusId`→`autoFocus` on the spawned panel.
  **Parent = dock's active session** lands as a top-level anchor (no `dock`-token nesting) — documented v1
  behavior; **parent = a popped chat** nests immediately right of it for free. i18n **append-only ×14**:
  `chat.{chatAboutThis,discussingPassage}`. `npm run build` green (TS ✓), eslint clean on touched files (exit
  0), ChatColumn 2/2, i18n parity ✓ (14/14). **Only Chunk 12 (media) remains in Plan D.**

- 2026-06-22: **Plan D COMPLETE** (Chunk 12 landed — media attachments). TS `MediaItem` mirror added to
  `lib/types/api.ts` (`{type,url,label,duration?}` — `url` is the backend `/api/chat/media/<f>` path);
  `WorkspaceChat.pending` **repointed** from the placeholder `ChatPendingMedia` to `MediaItem[]` (the old
  type had no `url` and was referenced nowhere — **removed**); `media?: MediaItem[]` added to **both**
  `SourceChatMessage` and `NotebookChatMessage` (dock feeds `NotebookChatMessage[]` into ChatPanel's
  `SourceChatMessage[]` prop) **and** `SendNotebookChatMessageRequest`. New `chatApi.uploadMedia(file)`
  (FormData → `POST /chat/media`; client.ts strips Content-Type). `chat-workspace-store` gained
  `addPending`/`removePending`/`clearPending`. `useNotebookChat.sendMessageTo` gained a 4th `media?` param
  threaded onto the optimistic human message **and** the `/chat/execute` body (`sendMessage` back-compat
  unchanged). `ChatPanel` (kept tight): three new props (`pending`/`onAddPending`/`onRemovePending`),
  `onSendMessage` widened to `(message, modelOverride?, media?)`, **media UI gated to `isDock`** (dock +
  popped, never source chat) — two ghost image/video buttons + hidden file inputs (upload happens **in
  ChatPanel** so dock+popped share it; toast on failure), removable pending chips (monospace + ✕),
  **Send-enable = text OR ≥1 pending**; user media tiles render **above** the bubble (right-aligned), AI
  tiles **below** the text (`mt-12px`, before citations — handoff order tool-use→answer→media→citations).
  New `components/source/MessageMedia.tsx`: 150×104px / radius-10 wrapping tiles; image=`<img>` cover
  (eslint `no-img-element` suppressed — runtime-resolved API host, no static next/image domain), video=
  `<video preload=metadata>` first-frame + centered 40px accent play button + duration pill (**derived
  client-side from `loadedmetadata`** since backend `duration=null`); filename monospace over a dark
  bottom gradient; click opens full media. Asset src resolved via `getApiUrl()` + the returned url (works
  for both the `''` rewrite base and an absolute host). `ChatDock`/`PoppedChatPanel` wire the per-chat
  pending state + **clear-on-send**; shared `deriveChatTitle(message, media, t)` (text→trunc-30, else
  single filename / `"{n} attachments"`) for the auto-title of a media-only first turn. i18n
  **append-only ×14**: `chat.{attachImage,attachVideo,removeAttachment,attachmentsCount,uploadFailed}`.
  **Agent path** = file references (Decision 9, no choke); **Esperanto path** = vision payload, but
  model-side image *viewing* stays **BLOCKED** on no local vision LM (same documented limit as Chunk 5).
  **Live-verified:** `POST /chat/media` (png) → exact `MediaItem` shape; `GET` round-trips (HTTP 200, bytes
  match), `..` traversal → 404 (safe). `npm run build` green (TS ✓), eslint clean on touched files (0
  errors), ChatColumn 2/2, i18n parity ✓ (14/14). **Plan D is COMPLETE — all 4 chunks ☑. Plan E (polish)
  is now unblocked.**
- 2026-06-22: **Plan E COMPLETE** (Chunk 13 landed — polish). **Animations:** added `@keyframes onb-pulse`
  (1.3s) + `@keyframes onb-flash` (1.7s accent ring) + `.onb-pulse`/`.source-flash` utilities to
  `globals.css` (append-only after A's token swap). **Reconciled — did NOT rebuild what the design system
  already ships:** the chevron rotate (.18s) was already a CSS transition in `ToolUseDisclosure` (Chunk 10);
  the dropdown rise-in already exists via shadcn `animate-in` (slide+fade) → honored the handoff's `onb-up`
  .14s by tuning the **dock model-picker** `SelectContent` to `duration-150` rather than layering a
  conflicting keyframe. **Citation→source-card flash:** `ChatPanel.handleReferenceClick` now, for
  `type==='source'`, locates the card via `[data-source-id]` (CSS.escape-guarded), `scrollIntoView` +
  `.source-flash` for 1700ms (reflow-restart on repeat clicks); **falls back to the existing `openModal`**
  when no card is mounted (panel collapsed / source off-page / standalone source chat); `note`/`insight`
  unchanged. `SourceCard` stamps `data-source-id={bare id}` (strips the `source:` prefix — matches the bare
  id MessageReferences passes; **id contract verified**: `SourceListResponse.id`/`Citation.id` are full-
  prefixed, `bareId()` strips). **Prompt-pin** (handoff §"Composer"): `ChatPanel` grows a tail spacer on a
  new **human** turn and smooth-scrolls that prompt to the top (re-run on 0/60/180/360ms timers); the AI
  reply leaves it pinned (answer grows below); tab-switch/history-load resets the spacer + jumps to latest.
  **Gated to the dock variant** (dock + popped share `ChatPanel`) — **standalone source chat keeps its
  bottom-scroll, untouched**. **Source status polish:** `SourceCard` status retinted from hardcoded
  blue/green/red to the handoff `--ready/--processing/--failed` tokens on `bg-panel-2`; processing state now
  shows a **pulsing dot** (`onb-pulse`, `bg-processing`) instead of the spinner. **Mobile (Q-mobile):** kept
  the existing **tabbed reduced layout** (Sources/Notes/Chat, pop-out disabled) as the plan-permitted
  "documented reduced layout" — a 3-card horizontal track is cramped at phone widths and the tabbed view is
  already built/usable; **no `page.tsx` change**. **i18n final sweep:** E added **no new strings** (all
  polish is non-textual); resolved the pre-existing dead-key debt by **removing `navigation.collect` +
  `navigation.manage` from all 14 locales** (Plan A's orphans — `process`/`create`/`workspace`/`system`
  remain, still referenced; append-only concurrency concern moot now that A–D are all landed). **Verify:**
  `npm run build` green (TS ✓), `eslint` exit 0 on touched files, **vitest 53/53** (i18n parity ×14 +
  unused-key detection + ChatColumn 2/2). Touched (minimal): `globals.css`, `ChatPanel.tsx`, `SourceCard.tsx`,
  `ChatDock.tsx`, `lib/locales/*` (×14). **All 5 plan rows are now ☑.**
- 2026-06-22: **All plans complete — archived 2026-06-22.** Moved every `ncw-*.md` plan file + this
  coordinator into `.claude/plans/archived/`.

## Context — why
The user wants the `design_handoff_notebook_chat/` design realized in the app: a **multi-pane chat
workspace** built around a notebook of sources + notes. Defining features: a horizontal **panel
track** of resizable/draggable/dockable cards (Sources, Notes, Chat Dock, popped chats); **sub-chats**
spun off from a highlighted passage; **media attachments** (images/videos) on messages; a **tool-use
disclosure** ("Searched your sources"); structured **citations** that flash the source card; and an
**in-dock model picker** for the Claude Agent. Warm-paper/indigo theme, light + dark.

This builds on the already-shipped **Claude Agent SDK** chat path (`claude-agent-integration`,
archived): chat can route through the local Claude CLI with in-process MCP tools that read
notebooks/sources/notes, and a model-selection backend + Settings card already exist.

**Current state (verified 2026-06-21/22):**
- **Theme:** single source of truth `frontend/src/app/globals.css` (`:root` 44–77, `.dark` 79–111),
  **Tailwind v4** CSS `@theme inline` (4–42), OKLCH values. Theme is a **custom Zustand store** (not
  next-themes): `theme-store.ts`, `ThemeProvider.tsx`, `theme-script.ts`, `ThemeToggle.tsx`. Every
  component uses **semantic tokens** (`bg-primary`, `bg-sidebar`, `text-foreground`…) → a reskin is a
  value swap, not a component rewrite. `Inter` is already imported in `app/layout.tsx:2,13` but
  `globals.css:7` still maps `--font-sans` to `--font-geist-sans` (mismatch to fix).
- **Shell:** `AppShell.tsx` (flex `h-screen`), `AppSidebar.tsx` (`w-64`/`w-16`, nav groups
  COLLECT/PROCESS/CREATE/MANAGE). Handoff wants **236px** + WORKSPACE/SYSTEM grouping.
- **Notebook page:** `app/(dashboard)/notebooks/[id]/page.tsx` — **fixed 3-column flex**
  (Sources|Notes|Chat), collapse-only via `notebook-columns-store`. **No resizable/dockable lib
  installed** (no react-resizable-panels / dnd-kit / re-resizable / react-rnd).
- **Chat:** two parallel systems — notebook-chat (`POST /chat/execute`, **non-streaming**) and
  source-chat (per-source, **SSE streaming**). UI shows **one** chat at a time. Message type is
  `{id,type,content,timestamp}` — no media/tool/structured-citation fields. No sub-chats, no
  multi-pane, no media.
- **Messages persist in a LangGraph SQLite checkpoint** (`./data/sqlite-db/checkpoints.sqlite`), NOT
  SurrealDB. `ChatSession` is a SurrealDB `chat_session` record (**SCHEMALESS**).
- **Claude agent** (`open_notebook/ai/claude_agent.py`): `_run` (141–179) collects only `TextBlock`
  and **discards `ToolUseBlock`/`ToolResultBlock`**; `_flatten` (113–138) is **text-only**;
  `generate_with_claude_agent` returns `AIMessage(content=text)` (no metadata, no id).
- **Citations:** plumbing exists end-to-end — prompts emit `[source:id]`/`[note:id]`/`[insight:id]`;
  `source-references.tsx` parses → numbered clickable refs + modal. **Gap is enrichment** (structured
  array, titles/snippets, followups), not basic plumbing.
- **Uploads:** `api/routers/sources.py` `save_uploaded_file` (73–94) → `./data/uploads`
  (`config.py:12`); download `GET /sources/{id}/download` (702–716). Frontend FormData via
  `sources.ts` + `client.ts` interceptor that strips Content-Type for multipart.
- **Model picker (backend done):** `GET/PUT /models/claude-agent` + `useClaudeAgentModel()` /
  `useUpdateClaudeAgentModel()` hooks + a Settings card. Options: Opus 4.8 / Sonnet 4.6 / Haiku 4.5 /
  aliases / "follow default". Stored as a **global singleton** `claude_agent` Model record.

## Decisions log (LAW — applies to all plans)
| # | Question | Decision |
|--:|----------|----------|
| 1 | Relationship to existing `subchat-linkage.md`? | **One merged effort.** Its sub-chat + citation chunks are folded into Plans B/D; that doc is superseded/archived. |
| 2 | Layout scope? | **Full workspace per handoff** — panel track with resize (240–980px), drag-reorder, pop-out/dock-back, double-click maximize, derived sub-chat nesting/order. (Not the side-sheet MVP the old plan chose.) |
| 3 | Theme scope? | **App-wide reskin** — replace the global token palette with the handoff warm-paper/indigo system across every page. |
| 4 | Media attachments? | **Included** — full-stack: composer attach UI, upload endpoint, message `media[]` schema, multimodal payload to the model. |
| 5 | Sub-chat persistence shape? | **Hybrid** — persist `parent_session_id` + `quote` as nullable `ChatSession` fields; keep `docked`/`width`/`draft`/`pending` client-only in Zustand. |
| 6 | How are `citations[]`/`followups[]` produced? | **Backend resolution of inline markers** (parse `[type:id]`, dedup, number, fetch title/snippet) + **prompt-emit + parse** for followups (`---FOLLOWUPS---` block). No fragile structured-JSON ask on the agent path. |
| 7 | Token value format? | **Use the handoff's exact hex values** in the CSS custom props (don't re-derive to OKLCH). Keep existing semantic token *names*; add new tokens for handoff-only roles. |
| 8 | Model picker placement vs the global singleton backend? | Surface the **existing global** `claude_agent` selection as a compact dock-header dropdown. Per-chat override is **deferred** (Open Q-permodel). |
| 9 | Claude-agent multimodal? | Agent transcript is text-only and SDK image support unverified. v1: media flows to the **Esperanto/LangChain** path; on the agent path attachments are **referenced as files**, not inlined. Full agent multimodal = Open Q-agentmedia. |
| 10 | Notebook-chat streaming for the prompt-pin "new turn" feel? | Keep notebook-chat **non-streaming** for v1. SSE adoption for notebook-chat = deferred. |

### Reconciliation — input artifact (handoff) → codebase
**Token mapping (Plan A Chunk 0 is the authority; this is the translation contract).** Handoff token →
existing semantic token (keep the name, set the handoff value). Light values shown; apply the handoff's
Dark table to `.dark`.
| Handoff token (light) | → existing semantic var | Notes |
|---|---|---|
| `--bg #f4f1e9` | `--background` | |
| `--panel #fffefb` | `--card`, `--popover` | card/popover surfaces |
| `--panel-2 #faf7f0` | `--secondary`, `--muted` | inset surfaces |
| `--text #34373c` | `--foreground`, `--card-foreground`, `--popover-foreground` | |
| `--text-2 #8d8a82` | `--muted-foreground` | |
| `--border #e7e1d4` | `--border`, `--input` | |
| `--nav-hover #e6e0d2` | `--accent`, `--sidebar-accent` | shadcn `--accent` = hover bg, **not** brand |
| `--accent #5b54d6` (indigo) | `--primary`, `--ring`, `--sidebar-primary` | the brand/CTA color |
| `--sidebar #efeadf` | `--sidebar` | |
| `--failed #c0524a` | `--destructive` | |
**Handoff tokens with NO existing equivalent → add new custom props** (and expose via `@theme inline`
as `--color-*` so utilities like `bg-panel-2`, `text-text-3`, `text-ready` exist):
`--panel-2` (distinct from secondary if needed), `--text-3 #a9a59b`, `--border-2 #efeae0`,
`--accent-soft rgba(91,84,214,.1)`, `--accent-soft-2 rgba(91,84,214,.16)`, `--ready #3f9d6b`,
`--processing #c08a2d`, `--failed #c0524a`, `--shadow` (the two-layer panel shadow).
**Drift flags:** (a) handoff radii are role-specific (panels 10–12, buttons 7–9, bubble
`14px 14px 4px 14px`) — current `--radius:0.65rem`; set `--radius:0.75rem` and use `radius-sm` for
buttons, hardcode the bubble radius. (b) Font mismatch (`globals.css:7`). (c) Sidebar width 236px vs
`w-64`. (d) handoff status colors (ready/processing/failed) have no current home → new tokens.

### Reconciliation — with `.claude/plans/pdf-viewer-citations.md` (active)
- That plan extends the citation token to **`[source:<id>#p=<n>]`** (page anchor). Plan B's Chunk 3
  resolver MUST tolerate the optional `#p=<n>` fragment, and the `Citation` schema MUST include an
  optional `page` field so the two features stack.
- Both touch `prompts/chat/system.jinja` and `source-references.tsx`. Whoever lands second **merges**:
  keep both the numbered-card rendering (ours) and the page-jump click target (theirs).
- **Migration numbering:** next free number is **16** (latest applied = 15). Both Plan B (Chunk 2)
  and the pdf plan add migrations. **Whoever lands first takes 16; the next takes 17.** Re-check
  `open_notebook/database/async_migrate.py` before claiming a number.

## Conventions / translation notes (apply to all plans)
- **Migrations:** numbered pairs `N.surrealql` + `N_down.surrealql` under
  `open_notebook/database/migrations/`, hard-registered in `open_notebook/database/async_migrate.py`
  (`AsyncMigrationManager.__init__`, ~98–123). `chat_session` is **SCHEMALESS** → new fields
  auto-persist; the migration is for versioning/rollback (write `REMOVE FIELD IF EXISTS` in the down).
- **Domain nullable fields:** add field names to `nullable_fields: ClassVar[set[str]]` so `None`
  persists (`_prepare_save_data` in `domain/base.py`). Declare `Optional[...] = None`. `model_override`
  is the **exact precedent** — copy its pattern through every layer.
- **Endpoint response mapping:** read new session fields with `getattr(session, "field", None)`
  (defensive against old records) — matches existing `model_override` handling.
- **Graph async bridging:** `call_model_with_messages` is a **sync** LangGraph node bridging to async
  via a new event loop / ThreadPool — don't `await` directly in the node; do DB work in the async
  router functions (`execute_chat`/`get_session` are already `async`).
- **Frontend:** Next.js 16 / React 19 / TS / Zustand / **TanStack Query** / **Tailwind v4** /
  shadcn(Radix) / **lucide-react** icons. API base `apiClient` in `src/lib/api/`; types in
  `src/lib/types/api.ts`. Theme is the **custom Zustand store**, not next-themes.
- **FormData uploads:** stringify nested JSON fields; the `client.ts` interceptor strips Content-Type
  for FormData so the browser sets the multipart boundary (reuse, don't reinvent).
- **i18n:** every new user-facing string needs translation keys across **all 14 locales**
  (`frontend/src/lib/locales/`: bn-IN, ca-ES, de-DE, en-US, es-ES, fr-FR, it-IT, ja-JP, pl-PL, pt-BR,
  ru-RU, tr-TR, zh-CN, zh-TW). Append-only — never delete another plan's keys. (This doc originally
  said "5 locales"; the repo has had 14 since before this effort — A/B/C/D-Chunk-9 all landed ×14.)
- **Run from source** (not Docker) for the Claude-agent path; checkpoint at `./data/sqlite-db/`.

## Deferred (documented, not built now)
- **Source-chat parity** ⊘ — the source-chat path is **SSE streaming**; citations/followups/tool-uses
  must be emitted as final stream events and sub-chat/media wired into `useSourceChat`.
- **Notebook-chat streaming** ⊘ — adopt the SSE pattern for `/chat/execute` if the synchronous reply
  feel proves insufficient (Decision 10).
- **Full Claude-agent multimodal** ⊘ — inline images into the agent transcript once SDK image support
  is verified (Open Q-agentmedia); v1 uses the Esperanto path + file references (Decision 9).
- **Per-chat model override** ⊘ — backend stores a global `claude_agent` selection (Decision 8).
- **Message-precise back-navigation** ⊘ — anchor a sub-chat to the exact parent *message*. Needs a
  stable AI-message id (today `AIMessage` has none; API falls back to positional `msg_{len}`). Cheap
  fix: `id=str(uuid4())` at construction. Not required for the hybrid design.

## Open Questions (surface to human; don't guess)
- **Q-nav** — Under the handoff's two groups (WORKSPACE/SYSTEM), where do the current extra nav items
  (Transformations, Advanced) go? *Default: under SYSTEM.* (Plan A, Chunk 1)
- **Q-dnd** — Drag library for reorder/pop-out: `@dnd-kit/core` vs native HTML5 DnD? *Default:
  `@dnd-kit/core`.* (Plan C, Chunk 8)
- **Q-toolnames** — Send raw MCP tool names and map in the UI, or pre-friendly on the backend?
  *Default: send raw, map in UI.* (Plans B/D, Chunks 4/10)
- **Q-agentmedia** — Does the Claude Agent SDK accept image content blocks in this version? *Default:
  Esperanto path for vision; agent = references (Decision 9).* (Plan B, Chunk 5)
- **Q-mobile** — Mobile shape for the panel track? *Default: horizontal scroll, same as desktop.*
  (Plans C/E, Chunks 6/13)
- **Q-mediastore** — Store chat media as standalone files only, or also as SurrealDB records? *Default:
  files under `data/uploads/chat-media/` + url on the message; no record in v1.* (Plan B, Chunk 5)

## Reference index (shared)
- **Primitives to reuse:** `model_override` end-to-end pattern; `nullable_fields`/`_prepare_save_data`
  (`domain/base.py`); migration pair format (`migrations/15.*`); inline marker regex + numbering
  (`source-references.tsx`); `handleReferenceClick`→`openModal`; FormData upload + `client.ts`
  interceptor; `save_uploaded_file`/`generate_unique_filename` + download guard; `useClaudeAgentModel`/
  `useUpdateClaudeAgentModel`; `AIMessage.additional_kwargs` carrier; the semantic-token theme system;
  `tw-animate-css`; `ui/collapsible`.
- **Deps available:** Next 16 / React 19 / TS / Zustand / TanStack Query / Tailwind v4 / shadcn(Radix)
  / lucide-react / ReactMarkdown (+remark-gfm/math, rehype-katex) / `tw-animate-css`. **To add:**
  `react-resizable-panels` (Plan C), `@dnd-kit/core` (Plan C, Chunk 8).
- **Confirmed APIs (2026-06-21/22):**
  - `api/routers/chat.py`: `CreateSessionRequest`@22, `UpdateSessionRequest`@30, `ChatMessage`@37,
    `ChatSessionResponse`@44, `ExecuteChatRequest`@64; `get_sessions`@96, `create_session`@137,
    `get_session`@175, `update_session`@250, `execute_chat`@330 (state 370–373; msg conversion 396–405;
    msg id fallback `getattr(msg,"id",f"msg_{len}")`).
  - `graphs/chat.py`: `ThreadState`@27, `_generate_ai_message`@35, `call_model_with_messages`@55
    (system prompt @57, payload `[SystemMessage]+messages` @58, return @94), `SqliteSaver` checkpoint.
  - `claude_agent.py`: imports @17–23 (add `ToolUseBlock`,`ToolResultBlock`); `_flatten`@113–138
    (text-only); `_run`@141–179 (collects only `TextBlock`); `generate_with_claude_agent`@182–210.
    MCP tools @`claude_agent_tools.py`: `list_notebooks`,`get_notebook`,`list_sources`,`get_source`,
    `get_note`,`search`; allowed `mcp__open_notebook__*`. `CLAUDE_AGENT_MODEL_OPTIONS` in `claude_agent.py`.
  - `ChatSession`@`domain/notebook.py:679` (`table_name="chat_session"`,
    `nullable_fields={"model_override"}`); `chat_session` SCHEMALESS (`migrations/3.surrealql`);
    migrations registered `async_migrate.py` ~98–123; latest = 15 → next **16**.
  - Uploads: `save_uploaded_file`@`sources.py:73–94`, `generate_unique_filename`@41–70,
    `UPLOADS_FOLDER`@`config.py:12`, download @702–716 (guard `_resolve_source_file` 588–610).
  - Frontend chat types `api.ts` (`BaseChatSession`@133, `SourceChatMessage`@147,
    `NotebookChatSession`@190, `NotebookChatMessage`@194, `CreateNotebookChatSessionRequest`@205);
    `chatApi`@`api/chat.ts:13` (`createSession`@23, `sendMessage`@51); hooks `useNotebookChat.ts`
    (`sendMessage`@176–248), `useSourceChat.ts` (SSE); model hooks `use-models.ts`
    (`useClaudeAgentModel`@120, `useUpdateClaudeAgentModel`@127).
  - Model picker backend (done): `GET/PUT /models/claude-agent` (`api/routers/models.py`).

## Completion & archival
When **all 5 plan rows are ☑ done** in the Cross-plan status table: append a Changelog line ("All
plans complete — archived <date>"), then move every `ncw-*.md` plan file **and** this coordinator to
`.claude/plans/archived/` and tell the user the feature is complete and archived.
