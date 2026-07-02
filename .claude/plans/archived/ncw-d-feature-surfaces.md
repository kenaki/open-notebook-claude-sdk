# Plan D — Chat Feature Surfaces (Notebook Multi-Chat Workspace)

> **One of 5 parallel plans.** Read `.claude/plans/notebook-chat-workspace.md` (the COORDINATOR) first
> for shared law: Decisions, Conventions, cross-plan status, and the backend JSON shapes Plan B defined
> (`Citation`, `ToolUseDisclosure`, `MediaItem`) — your TS types must mirror them exactly.
> **Chunks:** 9 (structured citations UI), 10 (tool-use disclosure UI), 11 (sub-chats), 12 (media UI).
> Frontend.
> **Dependencies:** **Plan B** (backend) and **Plan C** (dock/ChatPanel) must both be ☑ landed.
> Per-chunk backend deps: 9←Chunk3, 10←Chunk4, 11←Chunk2+Plan C Chunk8, 12←Chunk5. These 4 chunks
> are mostly independent of each other but all extend `ChatPanel.tsx` — do them **one per session** to
> keep edits to that file clean.
> **Input artifact:** `design_handoff_notebook_chat/README.md` (citations, sub-chats, media sections).

## Coordination (same working tree, sequential landing)
- **Wait for:** Plan B **and** Plan C both ☑ in coordinator. Check before starting.
- **Shared files (you extend what C built):** `components/source/ChatPanel.tsx`, `lib/types/api.ts`,
  `lib/hooks/useNotebookChat.ts`, `lib/api/chat.ts`. C landed first; you add to its base. Within Plan D,
  serialize the 4 chunks so `ChatPanel.tsx` edits don't stack unreviewed.
- **`lib/locales/*`:** append-only translation keys ("References", "Suggested follow-ups", "Searched
  your sources", "Chat about this", media labels). Never delete A's/E's keys.
- **Plan E (polish) runs after you** — leave the citation `handleReferenceClick` wired so E can add the
  source-card flash.
- When done: update coordinator Cross-plan status row "D" → ☑ + Changelog.

## Resume prompt (fresh chat)
> Execute Plan D (Chat Feature Surfaces) of the Notebook Multi-Chat Workspace. First confirm Plans B
> and C are ☑ in the coordinator. Read `.claude/plans/ncw-d-feature-surfaces.md` and the coordinator
> `.claude/plans/notebook-chat-workspace.md` in full (plus the handoff README). Do the next unstarted
> chunk (9, 10, 11, or 12), verify it, update this plan's Status + the coordinator's Cross-plan
> status/Changelog, and tell me when it's safe to clear context. One chunk per session.

## Status
| Chunk | Title | Status | Notes |
|------:|-------|--------|-------|
| 9 | Structured citations (CitationCard + followup chips) | ☑ done | `Citation` TS mirror + `citations?`/`followups?` on both msg types; `MessageReferences.tsx` (cards+chips); `appendReferenceList` flag on `convertReferencesToCompactMarkdown` suppresses dup list; i18n `chat.suggestedFollowups` ×14 |
| 10 | Tool-use disclosure ("Searched your sources") | ☑ done | `ToolUseDisclosure` TS mirror + `tool_uses?` on both msg types; new `components/source/ToolUseDisclosure.tsx` (ui/collapsible summary + chevron rotate .18s + per-call rows w/ friendly label + query/id detail); rendered **above** the AI bubble, gated on `tool_uses?.length` (null on Esperanto → nothing); raw-name→label map (search/source/note/notebook/default); i18n `chat.{searchedYourSources,readSources,readNote,readNotebook,usedTool}` ×14 |
| 11 | Sub-chats (selection → "Chat about this" → anchored panel) | ☑ done | `parent_session_id?`/`quote?` on `BaseChatSession` + `CreateNotebookChatSessionRequest`; `createSubChat(parentId,quote,title?)` in `useNotebookChat` (title=trunc quote ≤26+"…"); **`syncChats` upgraded to take session objects + hydrate persisted sub-chats as popped/anchored panels on reload** (closed a real gap — Chunk 8 nulled parent/quote); new `PassageSelectionMenu.tsx` (doc `mouseup`→`[data-chat-scope]`→fixed accent pill "Chat about this"+sparkle at selTop−46, portal to body, dismiss on outside-click/scroll); `ChatPanel` +`chatScopeId` (stamps `data-chat-scope` on AI bodies) +`autoFocus` (mount-only composer focus); `PoppedChatPanel` banner gains "DISCUSSING THIS PASSAGE" eyebrow + `autoFocus`; page mounts menu (desktop) + `pendingFocusId`; i18n `chat.{chatAboutThis,discussingPassage}` ×14 |
| 12 | Media attachments (composer attach → chips → tiles) | ☑ done | `MediaItem` TS mirror (repointed `WorkspaceChat.pending` to it; removed redundant `ChatPendingMedia`) + `media?` on both msg types + `SendNotebookChatMessageRequest`; `chatApi.uploadMedia` (FormData→`POST /chat/media`); store `addPending`/`removePending`/`clearPending`; `sendMessageTo` 4th `media` param (optimistic msg + `/chat/execute` body); `ChatPanel` ghost image/video buttons + pending chips + Send-enable (text OR ≥1 pending), gated `isDock` (dock+popped, not source chat); new `MessageMedia.tsx` (150×104 tiles, video first-frame poster + 40px play + duration derived client-side, filename over gradient; asset url = `getApiUrl()`+`/api/chat/media/<f>`); user media above bubble / AI below (mt-12px); `deriveChatTitle` (text→trunc, else filename / "{n} attachments"); i18n `chat.{attachImage,attachVideo,removeAttachment,attachmentsCount,uploadFailed}` ×14. Live: POST/GET media round-trip ✔ (bytes match, traversal-safe); model-side vision BLOCKED (no local vision LM — same as Chunk 5). build ✓ / eslint ✓ / ChatColumn 2/2 / i18n parity 14/14 |

---

### Chunk 9 — Structured citations (CitationCard + followup chips)
- **Goal:** AI replies render a numbered **reference card list** (title + snippet, click → existing
  modal) and **follow-up chips** (click → sends that question), driven by `citations[]`/`followups[]`;
  inline-marker parsing stays as fallback.
- **Read first:** `lib/types/api.ts` (`NotebookChatMessage`@194, `SourceChatMessage`@147);
  `components/source/ChatPanel.tsx` (`AIMessageContent`, `handleReferenceClick` ~88–99);
  `lib/utils/source-references.tsx` (`onReferenceClick` contract, `#ref-{type}-{id}` scheme);
  `lib/hooks/useNotebookChat.ts`; a `ui/` card/badge for styling.
- **Exact values:** mirror backend `Citation` in TS (`id,type,number,title?,snippet?,page?`).
- **Reuse:** keep `handleReferenceClick(type,id)`→`openModal`; the markdown renderer for `content`.
- **Steps:** (1) add `Citation` + `citations?`/`followups?` to the message types; (2) `CitationCard`/
  `MessageReferences` numbered list; (3) follow-up chips row; (4) wire into `ChatPanel` AI render (use
  cards if `citations?.length`, else inline fallback); carry fields through `useNotebookChat`; (5) i18n
  keys ("References", "Suggested follow-ups").
- **Verify:** a citing chat shows reference cards (titles/snippets), click opens the right modal;
  follow-up chips send; old sessions still render via fallback. `npm run build` passes.

### Chunk 10 — Tool-use disclosure
- **Goal:** AI messages from the Claude Agent show a collapsible **"Searched your sources"** disclosure
  listing which tools ran (friendly labels + the searched targets), driven by `tool_uses[]`.
- **Read first:** handoff README "Other chat UI" (121–125) + animations (chevron rotate, 144);
  `components/source/ChatPanel.tsx` (AI message render); `components/ui/collapsible.tsx`;
  Plan B Chunk 4's `ToolUseDisclosure` shape.
- **Exact values:** map raw `mcp__open_notebook__search` → "Searched your sources",
  `…get_source`/`…list_sources` → "Read source(s)", etc.; chevron rotate .18s.
- **Reuse:** `ui/collapsible` for the disclosure; lucide tool/chevron icons.
- **Steps:** (1) add `tool_uses?: ToolUseDisclosure[]` to the message type; (2) a `ToolUseDisclosure`
  component (summary line + expandable detail list); (3) render above the answer text when present;
  (4) i18n + tool-name→label map.
- **Verify:** an agent reply that searched sources shows the collapsible summary; expanding lists the
  tool calls/targets; non-agent replies show nothing. `npm run build` passes.

### Chunk 11 — Sub-chats (selection → "Chat about this" → anchored panel)
- **Goal:** Selecting text in any AI reply shows a floating **"Chat about this"** pill; clicking spawns
  a sub-chat (`parent_session_id`+`quote`) that **pops out as a panel anchored immediately right of its
  parent** (via Plan C Chunk 8's order algo), showing a "DISCUSSING THIS PASSAGE" banner + focused
  empty-state.
- **Read first:** handoff README "Sub-chats" (90–105); `components/source/ChatPanel.tsx` (AI body —
  attach `mouseup` + `data-chat-scope`); `lib/hooks/useNotebookChat.ts`; the Plan C
  `chat-workspace-store` + Chunk 8 order algo; `lib/types/api.ts`
  (`CreateNotebookChatSessionRequest`@205); `lib/api/chat.ts` `createSession`@23.
- **Exact values:** pill label "Chat about this" (+ sparkle); selection ≥2 chars; pill `position:fixed`,
  `top = selectionTop − 46px`, dismiss on outside-click/scroll; banner "DISCUSSING THIS PASSAGE"
  (accent-soft bg, 3px accent left-border, quote icon); title = truncated quote (≤26 chars + "…").
- **Reuse:** `createSession` already POSTs the body through (just add fields to the request type);
  `childChatsOf`/order from Plan C Chunk 8; render the existing `ChatPanel` inside the sub-chat panel.
- **Steps:** (1) add `parent_session_id?`/`quote?` to request + session types; (2) `createSubChat
  (parentId, quote, title?)` in `useNotebookChat`; (3) `mouseup` selection capture (text + caret rect +
  originating chat id via `[data-chat-scope]`); (4) floating pill at the rect; (5) on click → create +
  pop the sub-chat panel (popped, `parentId`+`quote` set), clear selection, focus composer; (6) quote
  banner + focused empty-state ("Ask anything about this passage").
- **Verify:** select AI text → pill appears at the selection → click → a sub-chat panel opens
  immediately right of its parent with the quote banner + focused empty-state; send → reply; reload →
  sub-chat persists and re-anchors; closing the parent promotes the orphan (still renders).
  `npm run build` passes.

### Chunk 12 — Media attachments (composer attach → chips → tiles)
- **Goal:** The composer can attach images/videos (→ pending chips → send), and messages render media
  **tiles** (150×104px, video play overlay + duration badge), wired to the Plan B Chunk 5 upload +
  send path.
- **Read first:** handoff README "Media attachments" (107–113) + "Composer" (115–119);
  `components/source/ChatPanel.tsx` (composer); `lib/api/sources.ts` + `lib/api/client.ts` (FormData
  pattern); Plan B Chunk 5's `POST /chat/media` + `MediaItem` shape; `lib/hooks/useNotebookChat.ts`
  send path.
- **Exact values:** tile 150×104px, radius 10px; filename monospace bottom-left over dark gradient;
  video → centered 40px play button + top-right duration pill; Send enabled when text **or** ≥1
  pending; user-message media right-aligned above bubble (max-width 82% dock), AI media below
  (margin-top 12px).
- **Reuse:** the FormData upload pattern (interceptor strips Content-Type); lucide image/video/play
  icons; the `chat-workspace-store` `pending[]` reserved in Plan C Chunk 7.
- **Steps:** (1) two ghost icon buttons (image/video) → file picker → upload via `POST /chat/media` →
  push to `pending[]`; (2) pending chip row (monospace name + ✕ remove); (3) on send, move `pending[]`
  → message `media[]`, clear pending, include in the `/chat/execute` body; (4) render media tiles in
  bubbles (image + video variants); (5) i18n for any labels.
- **Verify:** attach an image → chip appears → send → tile renders in the user bubble and the model
  responds about it (Esperanto vision model); attach a video → tile shows play overlay + duration;
  remove-before-send works; Send disabled only when empty. `npm run build` passes.

## Completion
When all four chunks are ☑: update the coordinator's Cross-plan status (row D → ☑) + Changelog,
announce "✅ Plan D complete — safe to clear context. Plan E (polish) may now start." then stop.
