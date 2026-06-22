import { create } from 'zustand'
import type { WorkspaceChat, MediaItem } from '@/lib/types/api'

// Minimal session shape syncChats needs to reconcile + hydrate sub-chats on
// reload. A subset of NotebookChatSession (id + persisted sub-chat fields).
export interface SyncChatSession {
  id: string
  parent_session_id?: string | null
  quote?: string | null
}

// Notebook Multi-Chat Workspace (Plan C / Chunk 7). Client-only layer over chat
// sessions: a "chat" is a session (Decision 5/8) — title/messages come from
// useNotebookChat; this store owns the workspace UI state (tab order, per-chat
// composer draft, docked/popped + width, sub-chat parent/quote). Intentionally
// NOT persisted — it mirrors the live session list each mount.

// Handoff default width for a popped-out chat panel (Chunk 8).
export const POPPED_CHAT_DEFAULT_WIDTH = 480

// The three fixed (always-present) anchor panels. The display-order algorithm
// (notebooks/[id]/page.tsx) seeds its anchor list from these; popped chats are
// appended/removed as they pop/dock. These are opaque layout tokens — they are
// not chats, they just share the same ordered list so the whole track reorders
// as one sortable sequence.
export const FIXED_PANEL_IDS = ['sources', 'notes', 'dock'] as const

function createChat(id: string): WorkspaceChat {
  return {
    id,
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
  activeChatId: string | null
  // Reconcile the workspace with the live session list: add entries for new
  // sessions, drop entries for removed ones, keep existing order and append new.
  // A session that carries `parent_session_id` (a persisted sub-chat) is
  // hydrated as a popped, anchored panel — this is how sub-chats survive a
  // reload, since the rest of this store is ephemeral (Plan D / Chunk 11).
  syncChats: (sessions: SyncChatSession[]) => void
  setActiveChat: (id: string | null) => void
  setDraft: (id: string, draft: string) => void
  // Composer media staging (Plan D / Chunk 12): items already uploaded via
  // POST /chat/media, held until the next send moves them onto the message.
  addPending: (id: string, item: MediaItem) => void
  removePending: (id: string, index: number) => void
  clearPending: (id: string) => void
  removeChat: (id: string) => void
  // Chunk 8 hooks (pop-out / dock-back / resize / reorder), kept here so the dock
  // and the track share one source of truth.
  setDocked: (id: string, docked: boolean) => void
  setChatWidth: (id: string, width: number) => void
  reorder: (order: string[]) => void
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
          // Existing entry wins — preserves live docked/popped/draft/quote state.
          chats[s.id] = state.chats[s.id]
        } else if (s.parent_session_id) {
          // Hydrate a persisted sub-chat as a popped panel anchored to its parent
          // (reload path — the page's display-order algo nests it / promotes it).
          chats[s.id] = {
            ...createChat(s.id),
            docked: false,
            parentId: s.parent_session_id,
            quote: s.quote ?? null,
          }
        } else {
          chats[s.id] = createChat(s.id)
        }
      }
      const order = [
        ...state.order.filter((id) => ids.includes(id)),
        ...ids.filter((id) => !state.order.includes(id)),
      ]
      // Drop anchor tokens for chats that no longer exist; keep the fixed panels.
      let panelOrder = state.panelOrder.filter(
        (id) => (FIXED_PANEL_IDS as readonly string[]).includes(id) || ids.includes(id)
      )
      // Ensure every popped chat (incl. hydrated sub-chats) has an anchor token,
      // otherwise the track wouldn't render it.
      for (const id of ids) {
        if (chats[id].docked === false && !panelOrder.includes(id)) {
          panelOrder = [...panelOrder, id]
        }
      }
      const activeChatId =
        state.activeChatId && ids.includes(state.activeChatId)
          ? state.activeChatId
          : (order[0] ?? null)
      return { chats, order, panelOrder, activeChatId }
    }),
  setActiveChat: (id) => set({ activeChatId: id }),
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
      const activeChatId = state.activeChatId === id ? (order[0] ?? null) : state.activeChatId
      return { chats, order, panelOrder, activeChatId }
    }),
  setDocked: (id, docked) =>
    set((state) => {
      const chat = state.chats[id]
      if (!chat) return {}
      // Popping appends the chat to the anchor track; docking removes it.
      const panelOrder = docked
        ? state.panelOrder.filter((o) => o !== id)
        : state.panelOrder.includes(id)
          ? state.panelOrder
          : [...state.panelOrder, id]
      return { chats: { ...state.chats, [id]: { ...chat, docked } }, panelOrder }
    }),
  setChatWidth: (id, width) =>
    set((state) => {
      const chat = state.chats[id]
      if (!chat) return {}
      return { chats: { ...state.chats, [id]: { ...chat, width } } }
    }),
  reorder: (order) => set({ order }),
  reorderPanels: (panelOrder) => set({ panelOrder }),
}))
