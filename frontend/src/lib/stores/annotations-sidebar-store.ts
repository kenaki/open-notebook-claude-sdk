import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * Collapse state of the highlights sidebar, per source.
 *
 * The Reader and PDF tabs each mount their own `AnnotationsSidebar`, and both
 * stay mounted once visited (SourceDetailContent's lazy-mount-then-keep-alive).
 * A store rather than per-instance state so collapsing on one tab is already
 * collapsed on the other — two instances of the same panel disagreeing across
 * a tab switch reads as a bug. Persisted so the choice survives a reload,
 * matching the sibling per-source tab and last-page preferences.
 */
interface AnnotationsSidebarState {
  collapsedBySource: Record<string, boolean>
  toggle: (sourceKey: string) => void
  setCollapsed: (sourceKey: string, collapsed: boolean) => void
}

/** Sidebars mounted without a source id share one bucket. */
export const GLOBAL_SIDEBAR_KEY = '__global__'

export const useAnnotationsSidebarStore = create<AnnotationsSidebarState>()(
  persist(
    (set) => ({
      collapsedBySource: {},
      toggle: (sourceKey) =>
        set((state) => ({
          collapsedBySource: {
            ...state.collapsedBySource,
            [sourceKey]: !state.collapsedBySource[sourceKey],
          },
        })),
      setCollapsed: (sourceKey, collapsed) =>
        set((state) => ({
          collapsedBySource: { ...state.collapsedBySource, [sourceKey]: collapsed },
        })),
    }),
    {
      name: 'annotations-sidebar-storage',
    }
  )
)
