import { create } from 'zustand'

/**
 * pdf-block-ingestion Track D8 — reader ↔ sidebar/chat jump bridge.
 *
 * Annotation reference pills live in the chat column (MessageList), while the
 * viewers that can jump to a highlight (PDFViewer / ReaderView) live inside
 * SourceDetailContent — different subtrees with no common owner short of the
 * page. Rather than thread a callback through both branches, SourceDetailContent
 * registers a per-source jump router here (it alone knows the active tab + holds
 * imperative handles to both viewers), and a pill calls `requestJump(sourceId,
 * annotationId)`. Keyed by source id so a stale registration can never hijack
 * another source's jumps. No-ops when nothing is registered (e.g. notebook chat,
 * which never carries annotation refs).
 */
type JumpHandler = (annotationId: string) => void

interface AnnotationJumpState {
  handlers: Record<string, JumpHandler>
  register: (sourceId: string, handler: JumpHandler) => void
  unregister: (sourceId: string) => void
  requestJump: (sourceId: string, annotationId: string) => void
}

export const useAnnotationJumpStore = create<AnnotationJumpState>((set, get) => ({
  handlers: {},
  register: (sourceId, handler) =>
    set((state) => ({ handlers: { ...state.handlers, [sourceId]: handler } })),
  unregister: (sourceId) =>
    set((state) => {
      if (!(sourceId in state.handlers)) return state
      const next = { ...state.handlers }
      delete next[sourceId]
      return { handlers: next }
    }),
  requestJump: (sourceId, annotationId) => {
    get().handlers[sourceId]?.(annotationId)
  },
}))
