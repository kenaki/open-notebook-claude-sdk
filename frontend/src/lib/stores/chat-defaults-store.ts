import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// Per-notebook chat defaults (Notebook Multi-Chat Workspace). Persisted to
// localStorage so a notebook remembers how its chats should behave across
// reloads — currently just the default model for *side chats* (annotative
// sub-chats spawned from a passage). The value is a model_override string in
// the same scheme as a session's own override (see ChatModelPicker): a
// "claude_agent::<model>" marker, a bare registered model id, or null to follow
// the global default.
interface ChatDefaultsState {
  // notebookId -> side-chat default model_override (null = follow global default)
  sideChatModel: Record<string, string | null>
  setSideChatModel: (notebookId: string, model: string | null) => void
}

export const useChatDefaultsStore = create<ChatDefaultsState>()(
  persist(
    (set) => ({
      sideChatModel: {},
      setSideChatModel: (notebookId, model) =>
        set((state) => ({
          sideChatModel: { ...state.sideChatModel, [notebookId]: model },
        })),
    }),
    {
      name: 'chat-defaults-storage',
    }
  )
)

// Read the side-chat default for a notebook outside React (e.g. inside a hook
// callback at creation time, where we don't want to subscribe). Returns null
// when unset → the new chat follows the global default.
export function getSideChatModel(notebookId: string): string | null {
  return useChatDefaultsStore.getState().sideChatModel[notebookId] ?? null
}
