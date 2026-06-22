import { create } from 'zustand'
import type { WorkspaceChat, MediaItem } from '@/lib/types/api'

// Minimal session shape syncChats needs to reconcile + hydrate sub-chats on
// reload. A subset of NotebookChatSession (id + persisted sub-chat fields).
export interface SyncChatSession {
  id: string
  parent_session_id?: string | null
  quote?: string | null
}

// Notebook Multi-Chat Workspace (Plan C / Chunk 7), reworked for the sidebar
// redesign (Chunk 2). Client-only layer over chat sessions: a "chat" is a
// session (Decision 5/8) — title/messages come from useNotebookChat; this store
// owns the workspace UI state (visibility, dock vs popped, per-chat composer
// draft, sub-chat parent/quote). Intentionally NOT persisted — it mirrors the
// live session list each mount (ephemeral default — see Q-hide-persistence).
//
// Visibility model (Chunk 2): every chat is `open` (rendered — the active main
// in the dock, or a popped panel in the track) or closed (open=false; reachable
// only via the sidebar for mains, or the side-chats control for side chats).
// Among open chats, `docked` distinguishes the single active main shown in the
// dock (docked=true) from popped side-by-side panels (docked=false).

// Handoff default width for a popped-out chat panel (Chunk 8).
export const POPPED_CHAT_DEFAULT_WIDTH = 480

// The three fixed (always-present) anchor panels. The display-order algorithm
// (notebooks/[id]/page.tsx) seeds its anchor list from these; popped chats are
// appended/removed as they pop/dock. These are opaque layout tokens — they are
// not chats, they just share the same ordered list so the whole track reorders
// as one sortable sequence.
export const FIXED_PANEL_IDS = ['sources', 'notes', 'dock'] as const
const FIXED = FIXED_PANEL_IDS as readonly string[]

function createChat(id: string): WorkspaceChat {
  return {
    id,
    open: false,
    docked: true,
    width: POPPED_CHAT_DEFAULT_WIDTH,
    draft: '',
    pending: [],
    parentId: null,
    quote: null,
  }
}

interface ChatWorkspaceState {
  chats: Record<string, WorkspaceChat>
  order: string[] // dock tab order (drag-reorderable, Chunk 8)
  // Anchor display order for the panel track: the fixed panels + any popped
  // chats, in left-to-right order. Drag-reordering panels rewrites this; the
  // page derives the final CSS order from it (nesting sub-chats under parents).
  panelOrder: string[]
  // The main chat currently shown in the dock body (only one at a time — there
  // are no tabs anymore). Null when no main is open (dock shows its empty state).
  activeChatId: string | null
  // Reconcile the workspace with the live session list: keep existing entries'
  // state, create CLOSED entries for new sessions (sidebar redesign — sessions
  // no longer auto-open), and, when nothing is open, open the most-recent main
  // so the dock isn't empty on first load.
  syncChats: (sessions: SyncChatSession[]) => void
  // Open a chat. Mains dock + become active (returning the previously-docked
  // main to the sidebar); side chats open as popped panels. Creates a missing
  // entry on the fly so it survives the create→refetch race.
  openChat: (id: string) => void
  // Open a chat as a popped panel regardless of kind (track "+", side-chats
  // control) — does not change the active main.
  popChat: (id: string) => void
  // Hide a chat (non-destructive): stops rendering it; mains return to the
  // sidebar, popped panels lose their track token. Chunk 3 wires the X to this.
  closeChat: (id: string) => void
  setDraft: (id: string, draft: string) => void
  // Composer media staging (Plan D / Chunk 12): items already uploaded via
  // POST /chat/media, held until the next send moves them onto the message.
  addPending: (id: string, item: MediaItem) => void
  removePending: (id: string, index: number) => void
  clearPending: (id: string) => void
  removeChat: (id: string) => void
  setChatWidth: (id: string, width: number) => void
  reorderPanels: (panelOrder: string[]) => void
}

export const useChatWorkspaceStore = create<ChatWorkspaceState>()((set) => ({
  chats: {},
  order: [],
  panelOrder: [...FIXED_PANEL_IDS],
  activeChatId: null,
  syncChats: (sessions) =>
    set((state) => {
      const ids = sessions.map((s) => s.id)
      const chats: Record<string, WorkspaceChat> = {}
      for (const s of sessions) {
        if (state.chats[s.id]) {
          // Existing entry wins for live UI state (open/docked/draft/pending),
          // but refresh the server-owned parent/quote so a promote (side → main)
          // reconciles: clearing parent_session_id drops the "discussing passage"
          // banner + promote affordance, which read parentId/quote (Chunk 5).
          chats[s.id] = {
            ...state.chats[s.id],
            parentId: s.parent_session_id ?? null,
            quote: s.quote ?? null,
          }
        } else if (s.parent_session_id) {
          // New side chat: closed, pre-configured to pop (docked:false) when
          // opened via the side-chats control (Chunk 4). Carries parent/quote.
          chats[s.id] = {
            ...createChat(s.id),
            docked: false,
            parentId: s.parent_session_id,
            quote: s.quote ?? null,
          }
        } else {
          // New main: closed (sidebar-only) until explicitly opened.
          chats[s.id] = createChat(s.id)
        }
      }
      const order = [
        ...state.order.filter((id) => ids.includes(id)),
        ...ids.filter((id) => !state.order.includes(id)),
      ]
      // Track anchors = fixed panels + every OPEN popped chat.
      let panelOrder = state.panelOrder.filter(
        (id) =>
          FIXED.includes(id) ||
          (ids.includes(id) && chats[id].open && chats[id].docked === false)
      )
      for (const id of ids) {
        if (chats[id].open && chats[id].docked === false && !panelOrder.includes(id)) {
          panelOrder = [...panelOrder, id]
        }
      }
      // First load (nothing open) → open the most-recent main so the dock isn't
      // empty. Sessions arrive updated-desc, so the first parentless one wins.
      const anyOpen = ids.some((id) => chats[id].open)
      let activeChatId =
        state.activeChatId && ids.includes(state.activeChatId) && chats[state.activeChatId].open
          ? state.activeChatId
          : null
      if (!anyOpen) {
        const recentMain = sessions.find((s) => !s.parent_session_id)
        if (recentMain) {
          chats[recentMain.id] = { ...chats[recentMain.id], open: true, docked: true }
          activeChatId = recentMain.id
        }
      }
      if (!activeChatId) {
        // Point the dock at an open docked main if one exists.
        activeChatId =
          order.find(
            (id) => chats[id]?.open && chats[id]?.docked !== false && !chats[id]?.parentId
          ) ?? null
      }
      return { chats, order, panelOrder, activeChatId }
    }),
  openChat: (id) =>
    set((state) => {
      // Tolerate a missing entry (sidebar "+" → create → refetch race): treat an
      // unknown id as a fresh main so the open lands immediately.
      const chat = state.chats[id] ?? createChat(id)
      if (chat.parentId) {
        // Side chat → popped panel; leave the active main untouched.
        const panelOrder = state.panelOrder.includes(id)
          ? state.panelOrder
          : [...state.panelOrder, id]
        return {
          chats: { ...state.chats, [id]: { ...chat, open: true, docked: false } },
          panelOrder,
        }
      }
      const chats = { ...state.chats, [id]: { ...chat, open: true, docked: true } }
      // Return the previously-active docked main to the sidebar (one docked main
      // at a time — there are no tabs).
      const prev = state.activeChatId
      if (prev && prev !== id && chats[prev] && chats[prev].docked !== false && !chats[prev].parentId) {
        chats[prev] = { ...chats[prev], open: false }
      }
      // Docking clears any stale panel token for this id.
      const panelOrder = state.panelOrder.filter((o) => o !== id)
      return { chats, panelOrder, activeChatId: id }
    }),
  popChat: (id) =>
    set((state) => {
      const chat = state.chats[id]
      if (!chat) return {}
      const panelOrder = state.panelOrder.includes(id)
        ? state.panelOrder
        : [...state.panelOrder, id]
      return { chats: { ...state.chats, [id]: { ...chat, open: true, docked: false } }, panelOrder }
    }),
  closeChat: (id) =>
    set((state) => {
      const chat = state.chats[id]
      if (!chat) return {}
      const chats = { ...state.chats, [id]: { ...chat, open: false } }
      const panelOrder = state.panelOrder.filter((o) => o !== id)
      let activeChatId = state.activeChatId
      if (activeChatId === id) {
        // Hand the dock to another open docked main, else leave it empty.
        activeChatId =
          state.order.find(
            (oid) =>
              oid !== id && chats[oid]?.open && chats[oid]?.docked !== false && !chats[oid]?.parentId
          ) ?? null
      }
      return { chats, panelOrder, activeChatId }
    }),
  setDraft: (id, draft) =>
    set((state) => {
      const chat = state.chats[id]
      if (!chat) return {}
      return { chats: { ...state.chats, [id]: { ...chat, draft } } }
    }),
  addPending: (id, item) =>
    set((state) => {
      const chat = state.chats[id]
      if (!chat) return {}
      return { chats: { ...state.chats, [id]: { ...chat, pending: [...chat.pending, item] } } }
    }),
  removePending: (id, index) =>
    set((state) => {
      const chat = state.chats[id]
      if (!chat) return {}
      return {
        chats: {
          ...state.chats,
          [id]: { ...chat, pending: chat.pending.filter((_, i) => i !== index) },
        },
      }
    }),
  clearPending: (id) =>
    set((state) => {
      const chat = state.chats[id]
      if (!chat || chat.pending.length === 0) return {}
      return { chats: { ...state.chats, [id]: { ...chat, pending: [] } } }
    }),
  removeChat: (id) =>
    set((state) => {
      if (!state.chats[id]) return {}
      const chats = { ...state.chats }
      delete chats[id]
      const order = state.order.filter((o) => o !== id)
      const panelOrder = state.panelOrder.filter((o) => o !== id)
      const activeChatId =
        state.activeChatId === id
          ? order.find(
              (oid) => chats[oid]?.open && chats[oid]?.docked !== false && !chats[oid]?.parentId
            ) ?? null
          : state.activeChatId
      return { chats, order, panelOrder, activeChatId }
    }),
  setChatWidth: (id, width) =>
    set((state) => {
      const chat = state.chats[id]
      if (!chat) return {}
      return { chats: { ...state.chats, [id]: { ...chat, width } } }
    }),
  reorderPanels: (panelOrder) => set({ panelOrder }),
}))
