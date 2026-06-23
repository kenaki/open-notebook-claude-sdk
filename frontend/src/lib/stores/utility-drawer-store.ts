import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// UI refactor — unified nav rail + single utility drawer. The global nav rail
// (AppSidebar) gets Sources/Notes toggle icons; clicking one slides a single
// drawer out immediately to the right of the rail. Toggling between Sources and
// Notes swaps the drawer's content rather than opening a second column, and
// re-clicking the active panel (or hitting close) slides the drawer shut so the
// chat canvas reclaims the horizontal space. Persisted so the choice survives a
// reload (the rail itself decides whether to honor it — only notebook routes
// have Sources/Notes content to show).

export type UtilityPanel = 'sources' | 'notes'

interface UtilityDrawerState {
  // The panel currently shown in the drawer, or null when the drawer is shut.
  panel: UtilityPanel | null
  // Toggle a panel: open it, swap to it, or (if already showing) close the drawer.
  togglePanel: (panel: UtilityPanel) => void
  // Force a specific panel open (no toggle-to-close).
  openPanel: (panel: UtilityPanel) => void
  // Slide the drawer shut.
  close: () => void
}

export const useUtilityDrawerStore = create<UtilityDrawerState>()(
  persist(
    (set) => ({
      panel: null,
      togglePanel: (panel) =>
        set((state) => ({ panel: state.panel === panel ? null : panel })),
      openPanel: (panel) => set({ panel }),
      close: () => set({ panel: null }),
    }),
    { name: 'utility-drawer-storage' }
  )
)
