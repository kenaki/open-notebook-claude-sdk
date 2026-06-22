import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// Panel-track layout (Notebook Multi-Chat Workspace, Plan C / Chunk 6).
export type PanelId = 'sources' | 'notes' | 'dock'

// Handoff default panel widths (px): Sources 296, Notes 316, Chat Dock 520.
export const PANEL_DEFAULT_WIDTHS: Record<PanelId, number> = {
  sources: 296,
  notes: 316,
  dock: 520,
}

// Resize clamp from the handoff spec.
export const PANEL_MIN_WIDTH = 240
export const PANEL_MAX_WIDTH = 980

interface NotebookColumnsState {
  sourcesCollapsed: boolean
  notesCollapsed: boolean
  // Per-panel widths (px) for the resizable track.
  widths: Record<PanelId, number>
  // The panel/chat currently maximized (double-click header), or null. Keyed by
  // PanelId ('sources'/'notes'/'dock') OR a popped chat's session id (Chunk 8) —
  // hence `string`, not `PanelId`.
  maximized: string | null
  toggleSources: () => void
  toggleNotes: () => void
  setSources: (collapsed: boolean) => void
  setNotes: (collapsed: boolean) => void
  setWidth: (panel: PanelId, width: number) => void
  toggleMaximized: (id: string) => void
  setMaximized: (id: string | null) => void
}

export const useNotebookColumnsStore = create<NotebookColumnsState>()(
  persist(
    (set) => ({
      sourcesCollapsed: false,
      notesCollapsed: false,
      widths: { ...PANEL_DEFAULT_WIDTHS },
      maximized: null,
      toggleSources: () => set((state) => ({ sourcesCollapsed: !state.sourcesCollapsed })),
      toggleNotes: () => set((state) => ({ notesCollapsed: !state.notesCollapsed })),
      setSources: (collapsed) => set({ sourcesCollapsed: collapsed }),
      setNotes: (collapsed) => set({ notesCollapsed: collapsed }),
      setWidth: (panel, width) =>
        set((state) => ({
          widths: {
            ...state.widths,
            [panel]: Math.max(
              PANEL_MIN_WIDTH,
              Math.min(PANEL_MAX_WIDTH, Math.round(width))
            ),
          },
        })),
      toggleMaximized: (id) =>
        set((state) => ({ maximized: state.maximized === id ? null : id })),
      setMaximized: (id) => set({ maximized: id }),
    }),
    {
      name: 'notebook-columns-storage',
    }
  )
)
