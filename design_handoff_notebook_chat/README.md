# Handoff: Open Notebook — Multi-Chat Workspace (with sub-chats & media attachments)

## Overview
"Open Notebook" is a research workspace built around a notebook of **sources** (uploaded PDFs, web links, audio) and **notes**, plus a **chat** area where the user asks Claude questions that are grounded in those sources. The defining feature is that **chat is multi-pane**: the user can run several chats at once, dock them as tabs or pop them out side-by-side, spin off **sub-chats** from a highlighted passage, and attach **images and videos** to messages.

This document is self-contained: a developer who was not present for the design conversation should be able to rebuild it from this README alone.

## About the Design Files
The files in this bundle are **design references created in HTML** — a working prototype showing intended look and behavior, **not production code to copy directly**. The build technology here is a small in-house template/logic runtime (`support.js` + a `.dc.html` file); **do not port that runtime.** Your task is to **recreate this UI in the target codebase's existing environment** (React, Vue, Svelte, SwiftUI, etc.) using its established components, state management, and styling conventions. If no environment exists yet, pick the most appropriate framework and implement there.

- `Open Notebook.dc.html` — the full prototype (markup + logic in one file). Open it in a browser to interact with it.
- `support.js` — the prototype's runtime. **Reference only; do not port.**

### How to read the prototype file
`Open Notebook.dc.html` has two halves:
1. **Template** (inside `<x-dc>…</x-dc>`) — markup with `{{ value }}` holes and `<sc-if>` / `<sc-for>` control-flow tags. Read this for layout and structure.
2. **Logic** (inside `<script type="text/x-dc">`, `class Component`) — a React-class-like component. `state` is the data model; `renderVals()` returns everything the template binds to. Read this for behavior and the data model.

## Fidelity
**High-fidelity.** Final colors, typography, spacing, radii, and interactions are all specified here and in the file. Recreate the UI pixel-accurately using your codebase's libraries. Exact values are in **Design Tokens** below.

---

## Layout (top level)
Full-viewport (`100vh`), no page scroll. Horizontal composition:

```
┌────────┬──────────────────────────────────────────────────────────┐
│        │  HEADER (title · "Notebook" badge · source/note count ·   │
│ SIDEBAR│          collapsed-panel chips · theme toggle)            │
│ 236px  ├──────────────────────────────────────────────────────────┤
│        │  PANEL TRACK  (horizontal flex row, overflow-x:auto,      │
│        │   gap:16px, padding:16px 24px 18px)                       │
│        │   ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐       │
│        │   │ SOURCES │ │  NOTES  │ │   CHAT   │ │ POPPED   │  …    │
│        │   │  panel  │ │  panel  │ │   DOCK   │ │ CHAT(s)  │       │
│        │   └─────────┘ └─────────┘ └──────────┘ └──────────┘       │
└────────┴──────────────────────────────────────────────────────────┘
```

- **Sidebar** (236px, fixed): brand, "New" button, WORKSPACE nav (Sources, Notebooks, Ask & Search, Podcasts), SYSTEM nav (Models, Settings). Collapsible via header menu button.
- **Panel track**: a horizontal, independently-scrolling row of resizable panels. Each panel is a rounded card (`border-radius:12px`, `1px` border, soft shadow). The panels are **Sources**, **Notes**, the **Chat Dock**, and any number of **popped-out chat panels**. Order is user-controlled (drag) and each panel is width-resizable (drag edges) and maximizable (double-click header).

All panels share the same shell: `position:relative; display:flex; flex-direction:column; background:var(--panel); border:1px solid var(--border); border-radius:12px; box-shadow:var(--shadow); overflow:hidden`. Default widths: Sources 296px, Notes 316px, Dock 520px, popped chat 480px. Resize clamps to **240–980px**.

---

## The Chat system (the core of this handoff)

There is **one flat list of chats** in state. Each chat is the same shape whether it's a dock tab, a popped panel, or a sub-chat — behavior differs only by a few fields.

### Chat data model
```js
{
  id:       string,          // unique
  title:    string,          // tab/panel label; auto-derived from first message if "New chat"
  docked:   boolean,         // true → lives as a tab in the Chat Dock; false → its own side panel
  width:    number,          // panel width in px when popped (default 480)
  draft:    string,          // current composer text
  pending:  MediaItem[],     // attachments staged in the composer, not yet sent
  messages: Message[],
  // sub-chat only:
  parentId: string|null,     // id of the chat this was spun off from (absent/null for top-level)
  quote:    string,          // the highlighted passage that seeded this sub-chat
}

Message = {
  id: string,
  role: 'user' | 'ai',
  text: string,
  media?: MediaItem[],       // attachments sent with the message
  // ai-only extras:
  tool?: { summary:string, details:{type:'check'|'search', text:string}[] },
  citations?: { icon:'file'|'web', label:string, sourceId:string }[],
}

MediaItem = {
  type: 'image' | 'video',
  label: string,             // filename, shown monospace
  duration?: string,         // video only, "m:ss"
}
```

### Docked vs. popped
- **Docked** chats (`docked:true`) appear as **tabs** in the Chat Dock panel; only the active tab (`activeChatId`) renders its conversation. Tabs are drag-reorderable; each has pop-out (↗) and close (✕) buttons.
- **Popped** chats (`docked:false`) render as **standalone side-by-side panels** in the track, each with its own header (dock-back ⤵ and close ✕), conversation, and composer.
- Transitions: **pop out** (`docked:true→false`), **dock back** (`false→true`). Dragging a tab out reveals a dashed **drop zone** ("Drop here to open side by side"); dropping pops the chat out.
- Closing is blocked when only one chat remains (always keep ≥1).

### Sub-chats (chat-about-a-passage)
This is the headline interaction. **A sub-chat is just a chat with `parentId` + `quote` set.** There is no separate type and no nested data — the parent/child relationship is derived at render time from `parentId`.

**Creation flow:**
1. **Selection capture** — a `mouseup` handler on every AI message body reads `window.getSelection()`. If the selection is ≥2 chars, it records: the selected text, the caret's bounding rectangle (for menu placement), and **which chat the selection came from** by walking up to the nearest element tagged with the chat's id (`data-chat-scope` in the prototype) → stored as the prospective `parentId`.
2. **Floating menu** — a small **"Chat about this"** button (accent-filled pill with a sparkle icon) renders at the selection, `position:fixed`, centered above the selection (`top = selectionTop − 46px`). It dismisses on outside-click or scroll.
3. **Spawn** — clicking it pushes a new chat with: `parentId` = captured chat id, `quote` = selected text, `title` = truncated quote (≤26 chars + "…"), `docked:false`, empty `messages`. The text selection is cleared and the new chat's composer is focused.

**Rendering a sub-chat:** popped panels with a `quote` show a **"DISCUSSING THIS PASSAGE"** banner at the top of the conversation (accent-soft background, 3px accent left-border, quote icon, the quoted text). The empty-state copy becomes "Ask anything about this passage" instead of "Ask about this notebook".

**Ordering / nesting (important — easy to get wrong):** display order is **computed, not stored**. The algorithm:
- Build a list of **anchors**: the visible Sources panel, Notes panel, the Dock, plus any popped chats that do **not** have a currently-present parent (`hasPresentParent` = parent exists and is itself docked or popped).
- A recursive `layout(token)` walks each anchor and **inserts each chat's child chats immediately after it** (`childChatsOf` = popped chats whose `parentId` matches). Sub-sub-chats nest further. The flattened sequence assigns each panel a CSS `order`.
- **Orphan fallback:** if a sub-chat's parent was closed, `hasPresentParent` is false, so it's promoted to a top-level anchor and still renders (never disappears).

The net effect: a sub-chat always sits **immediately to the right of the chat it came from**.

### Media attachments (images & videos)
Users attach images/videos to a message from the composer.

- The composer has two ghost icon buttons left of the textarea: **image** and **video**. Clicking one appends a `MediaItem` to the chat's `pending[]` (prototype uses a placeholder name like `image-1.png` / `clip-1.mp4`; videos get a random `m:ss` duration — in production these come from a real file picker / upload).
- **Pending row:** staged attachments render as removable chips above the input row (monospace filename + ✕). The **Send** button enables when there is **either** text **or** ≥1 pending attachment.
- **On send:** `pending[]` moves onto the new user message's `media[]` and `pending` clears. If the message has no text, the chat title falls back to the filename (or "N attachments").
- **Rendering media in a bubble:** each item is a **150×104px tile**, `border-radius:10px`, with a diagonal hatch placeholder background (in production, the real thumbnail). The filename sits bottom-left over a dark gradient (monospace, white). **Video** tiles additionally show a centered circular **play** button (40px, accent bg) and a **duration badge** top-right (dark pill, monospace). Tiles wrap (`flex-wrap`). In **user** messages they're right-aligned above the text bubble (`max-width:82%` docked / `84%` popped); in **AI** messages they appear below the text (`margin-top:12px`).

### Composer behavior
- Multiline auto-grow textarea, capped at 140px (dock) / 120px (popped), then scrolls.
- **⌘↵ / Ctrl+↵** sends (hint shown under the dock composer).
- On send the user's prompt is **pinned to the top** of the viewport (new-turn feel): a tail spacer is grown so the prompt can scroll to the top even when the answer is short, then the container smooth-scrolls the prompt near the top. (See `pinPrompt` for the exact technique — it re-runs on a few timers to survive reflow and tab-backgrounding.)
- The prototype fakes an AI reply ~750ms after send. Replace with your real streaming response.

### Other chat UI
- **Model picker** in the dock header (claude-agent / claude-sonnet / claude-opus) with a dropdown.
- **Context meter** pill ("4 sources · 2 notes · 12k tokens").
- **AI messages** can show: a collapsible **tool-use** disclosure ("Searched your sources" + expandable detail list of checked sources / search queries), the answer text, attached media, and **citation** chips (file/web icon + label) that **flash the referenced source card** in the Sources panel when clicked.
- **Empty state**: sparkle icon, title, helper line, and 3 suggestion buttons that send preset prompts.

---

## Sources & Notes panels (supporting context)
- **Sources panel**: search box; cards showing an icon (file/web/audio), title (2-line clamp), meta ("PDF · 488 pp"), a **status** indicator (Ready / Processing [pulsing dot] / Failed), and a 3-way **context toggle** (Insights / Full / Off) controlling how that source feeds the chat. "Add" appends a source that simulates processing→ready.
- **Notes panel**: cards with an **AI** or **You** tag, title, 3-line body clamp, timestamp. "Add" prepends a new note. AI answers and chat annotations can be saved as notes.
- Both panels can be **minimized** to a header chip (with count) and re-expanded.

---

## Interactions & Behavior summary
- **Sidebar**: collapse/expand; nav item selection (active highlight).
- **Theme**: light/dark toggle (full token swap — see below).
- **Panels**: drag header to reorder; drag left/right edge to resize (240–980px); double-click header to maximize (focused panel flexes to fill, its sub-chats stay visible at fixed width, everything else hides); minimize/expand Sources & Notes.
- **Chats**: new; switch active tab; drag-reorder tabs; pop out (incl. via drag to drop-zone); dock back; close (≥1 enforced).
- **Sub-chats**: select AI text → "Chat about this" → spawns a quoted side-panel chat anchored next to its parent.
- **Media**: attach image/video → chip in composer → remove or send → renders as tile (video gets play overlay + duration).
- **Citations**: click → corresponding source card flashes (accent ring, 1.7s).
- **Animations**: processing dot pulse (`onb-pulse`, 1.3s); dropdown rise-in (`onb-up`, .14s); prompt pin smooth-scroll; chevron rotate on disclosures (.18s).

## State Management
Single component state object. Key fields:
`theme`, `model`, `modelMenu`, `nav`, `sidebarOpen`, `sourceQuery`, `openTools{}`, `activeChatId`, `dragChatId`, `dragPanel`, `selMenu` (`{x,y,text,parentId}`), `maximized`, `order` (`['sources','notes','dock']`), `collapsed{sources,notes}`, `widths{sources,notes,dock}`, `resizing`, `sources[]`, `notes[]`, `chats[]` (the model above).

Derived at render time (do not store): panel display order & CSS `order`, anchor list, sub-chat nesting, maximize focus set, header chips, dock tabs, active dock view, popped panels.

Data fetching: none in the prototype. In production, wire: source upload/processing, real chat completions (streaming), file uploads for media, and note persistence.

## Design Tokens

### Colors — Light (default)
| Token | Value | Use |
|---|---|---|
| `--bg` | `#f4f1e9` | app background (warm paper) |
| `--panel` | `#fffefb` | panel/card surface |
| `--panel-2` | `#faf7f0` | inset surfaces (inputs, chips, sub-cards) |
| `--sidebar` | `#efeadf` | sidebar bg |
| `--text` | `#34373c` | primary text |
| `--text-2` | `#8d8a82` | secondary text |
| `--text-3` | `#a9a59b` | tertiary / icons / meta |
| `--border` | `#e7e1d4` | borders |
| `--border-2` | `#efeae0` | subtle borders |
| `--nav-hover` | `#e6e0d2` | nav hover |
| `--accent` | `#5b54d6` | primary (indigo) |
| `--accent-soft` | `rgba(91,84,214,.1)` | accent tint |
| `--accent-soft-2` | `rgba(91,84,214,.16)` | accent tint (stronger) |
| `--ready` | `#3f9d6b` | status: ready |
| `--processing` | `#c08a2d` | status: processing |
| `--failed` | `#c0524a` | status: failed |
| `--shadow` | `0 1px 2px rgba(40,35,20,.04), 0 2px 10px rgba(40,35,20,.04)` | panel shadow |

### Colors — Dark
| Token | Value |
|---|---|
| `--bg` | `#161519` |
| `--panel` | `#211f27` |
| `--panel-2` | `#1b1a21` |
| `--sidebar` | `#1a181e` |
| `--text` | `#e9e7ef` |
| `--text-2` | `#9b97a4` |
| `--text-3` | `#6f6b78` |
| `--border` | `rgba(255,255,255,.08)` |
| `--border-2` | `rgba(255,255,255,.05)` |
| `--nav-hover` | `rgba(255,255,255,.05)` |
| `--accent` | `#8b84f0` |
| `--accent-soft` | `rgba(139,132,240,.16)` |
| `--accent-soft-2` | `rgba(139,132,240,.26)` |
| `--ready` | `#5cc28c` |
| `--processing` | `#d9a94e` |
| `--failed` | `#e0726a` |
| `--shadow` | `0 1px 2px rgba(0,0,0,.3), 0 6px 18px rgba(0,0,0,.22)` |

### Typography
- Family: **Inter** (`Inter, system-ui, sans-serif`), antialiased. Weights used: 400, 450/500, 550/600, 700.
- Sizes: page base 14px; H1 19px/600; panel titles 13px/600; body/message 13.5px (line-height 1.5–1.62); secondary 12.5px; meta/labels 10.5–11px; section eyebrows 10.5px/600 letter-spacing .07em.
- Monospace (filenames, duration, kbd): `ui-monospace, Menlo, monospace`.

### Spacing / radii / sizing
- Panel padding ~14px; track gap 16px; track padding `16px 24px 18px`.
- Radii: panels/cards 10–12px; buttons/inputs 7–9px; pills 5–8px / 20px; message bubble `14px 14px 4px 14px`; media tile 10px.
- Icon buttons 26–34px square. Media tile **150×104px**. Avatar/icon chips 22–30px.
- Resize clamp 240–980px. Default widths: Sources 296 / Notes 316 / Dock 520 / popped chat 480.

### Icons
All icons are inline SVG (24×24, 1.7 stroke; a few are filled: sparkle, logo, grip, play). The set includes: logo, plus, search, sun, moon, file, web, audio, **image, video, play**, send, chevron(s), menu, minimize, x, pen, quote, tool, popout, dockin, grip, sparkle, sources, notebooks, ask, podcast, models, settings. Replace with your codebase's icon library — match the same metaphors.

## Assets
No external image/font assets beyond the **Inter** webfont (Google Fonts) and inline SVG icons. Media tiles use placeholder hatch backgrounds + filenames; **in production these are real user-uploaded image thumbnails / video posters**.

## Files
- `Open Notebook.dc.html` — full prototype (template + logic).
- `support.js` — prototype runtime (reference only; do not port).

## Build priority suggestion
1. Panel shell + track (Sources, Notes, Dock) with the token system & theming.
2. Chat data model + dock tabs + composer + message rendering.
3. Pop-out / dock-back / drag-reorder / maximize / resize.
4. **Sub-chats** (selection → "Chat about this" → quoted side panel + nesting/order algorithm).
5. **Media attachments** (composer attach → pending chips → message tiles with video overlay).
6. Tool-use disclosure, citations→source flash, notes/annotations.
