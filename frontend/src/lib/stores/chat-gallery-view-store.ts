import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// Persisted layout preference for the notebook Chat Gallery: a roomy card
// "grid" vs. a compact "list". Mirrors notebook-view-store so the toggle sticks
// across navigations and reloads.
export type ChatGalleryViewMode = 'grid' | 'list'

interface ChatGalleryViewState {
  viewMode: ChatGalleryViewMode
  setViewMode: (mode: ChatGalleryViewMode) => void
}

export const useChatGalleryViewStore = create<ChatGalleryViewState>()(
  persist(
    (set) => ({
      viewMode: 'grid',
      setViewMode: (mode) => set({ viewMode: mode }),
    }),
    {
      name: 'chat-gallery-view-storage',
    }
  )
)
