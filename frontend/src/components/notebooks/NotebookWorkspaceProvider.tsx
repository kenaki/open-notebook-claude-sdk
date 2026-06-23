'use client'

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useNotebook } from '@/lib/hooks/use-notebooks'
import { useNotebookSources } from '@/lib/hooks/use-sources'
import { useNotes } from '@/lib/hooks/use-notes'
import { useNotebookChat } from '@/lib/hooks/useNotebookChat'
import { useChatWorkspaceStore } from '@/lib/stores/chat-workspace-store'
import {
  applyBulkSourceContext,
  applyBulkNoteContext,
  computeSourceSelections,
  computeNoteSelections,
  type SourceContextDefault,
  type SourceBulkAction,
  type NoteContextDefault,
} from '@/lib/utils/source-context'
import type { ContextMode, ContextSelections } from '@/lib/types/notebook-context'
import type { NotebookResponse, SourceListResponse, NoteResponse } from '@/lib/types/api'

// Shared per-notebook workspace state (UI refactor). Previously this all lived
// inline in notebooks/[id]/page.tsx; it's now lifted into a provider mounted by
// notebooks/[id]/layout.tsx so it persists across the Gallery ↔ Deep-Dive route
// transition AND is reachable from the global utility drawer (Sources/Notes),
// which renders outside the route subtree (in AppShell). The single multiplexed
// chat hook lives here too: the Gallery needs `mainSessions`/`sideSessionsOf` to
// build cards, and the Deep-Dive needs the live message streams — one instance
// serves both.

interface ContextStats {
  sourcesInsights: number
  sourcesFull: number
  notesCount: number
  tokenCount: number
  charCount: number
}

interface NotebookWorkspaceValue {
  notebookId: string
  notebook: NotebookResponse | undefined
  notebookLoading: boolean

  sources: SourceListResponse[] | undefined
  sourcesLoading: boolean
  refetchSources: () => void
  hasNextPage: boolean
  isFetchingNextPage: boolean
  fetchNextPage: () => void

  notes: NoteResponse[] | undefined
  notesLoading: boolean

  contextSelections: ContextSelections
  handleContextModeChange: (itemId: string, mode: ContextMode, type: 'source' | 'note') => void
  handleBulkSourceContext: (action: SourceBulkAction) => void
  handleBulkNoteContext: (action: NoteContextDefault) => void

  chat: ReturnType<typeof useNotebookChat>
  contextStats: ContextStats
  // True when neither sources nor notes loaded at all (hard failure).
  dataError: boolean
}

const NotebookWorkspaceContext = createContext<NotebookWorkspaceValue | null>(null)

/**
 * Read the shared notebook workspace state. Returns `null` outside a notebook
 * route (e.g. the global drawer rendered on a non-notebook page), so callers can
 * gate their UI on it.
 */
export function useNotebookWorkspace(): NotebookWorkspaceValue | null {
  return useContext(NotebookWorkspaceContext)
}

/**
 * Same as {@link useNotebookWorkspace} but throws when missing — for components
 * that are only ever rendered inside the provider (Gallery / Deep-Dive).
 */
export function useNotebookWorkspaceStrict(): NotebookWorkspaceValue {
  const value = useContext(NotebookWorkspaceContext)
  if (!value) {
    throw new Error('useNotebookWorkspaceStrict must be used within a NotebookWorkspaceProvider')
  }
  return value
}

export function NotebookWorkspaceProvider({
  notebookId,
  children,
}: {
  notebookId: string
  children: ReactNode
}) {
  const { data: notebook, isLoading: notebookLoading } = useNotebook(notebookId)
  const {
    sources,
    isLoading: sourcesLoading,
    refetch: refetchSources,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useNotebookSources(notebookId)
  const { data: notes, isLoading: notesLoading } = useNotes(notebookId)

  // Context selection state (which sources/notes feed the chat, and in what mode).
  const [contextSelections, setContextSelections] = useState<ContextSelections>({
    sources: {},
    notes: {},
  })
  // Default mode applied to sources/notes as they page in, so a bulk action
  // (#223/#915) carries to later-loaded items instead of reverting to included.
  const [sourceContextDefault, setSourceContextDefault] = useState<SourceContextDefault>('include')
  const [noteContextDefault, setNoteContextDefault] = useState<NoteContextDefault>('include')

  useEffect(() => {
    if (sources && sources.length > 0) {
      setContextSelections((prev) => ({
        ...prev,
        sources: computeSourceSelections(prev.sources, sources, sourceContextDefault),
      }))
    }
  }, [sources, sourceContextDefault])

  useEffect(() => {
    if (notes && notes.length > 0) {
      setContextSelections((prev) => ({
        ...prev,
        notes: computeNoteSelections(prev.notes, notes, noteContextDefault),
      }))
    }
  }, [notes, noteContextDefault])

  // Popped side chats live in the workspace store; their message streams must be
  // kept live alongside the dock's active main (multiplexed hook).
  const wsChats = useChatWorkspaceStore((s) => s.chats)
  const poppedIds = useMemo(
    () => Object.keys(wsChats).filter((id) => wsChats[id]?.open && wsChats[id]?.docked === false),
    [wsChats]
  )

  const chat = useNotebookChat({
    notebookId,
    sources: sources ?? [],
    notes: notes ?? [],
    contextSelections,
    visibleSessionIds: poppedIds,
  })

  const contextStats = useMemo<ContextStats>(() => {
    let sourcesInsights = 0
    let sourcesFull = 0
    let notesCount = 0
    ;(sources ?? []).forEach((source) => {
      const mode = contextSelections.sources[source.id]
      if (mode === 'insights') sourcesInsights++
      else if (mode === 'full') sourcesFull++
    })
    ;(notes ?? []).forEach((note) => {
      if (contextSelections.notes[note.id] === 'full') notesCount++
    })
    return {
      sourcesInsights,
      sourcesFull,
      notesCount,
      tokenCount: chat.tokenCount,
      charCount: chat.charCount,
    }
  }, [sources, notes, contextSelections, chat.tokenCount, chat.charCount])

  const handleContextModeChange = (
    itemId: string,
    mode: ContextMode,
    type: 'source' | 'note'
  ) => {
    setContextSelections((prev) => ({
      ...prev,
      [type === 'source' ? 'sources' : 'notes']: {
        ...(type === 'source' ? prev.sources : prev.notes),
        [itemId]: mode,
      },
    }))
  }

  const handleBulkSourceContext = (action: SourceBulkAction) => {
    setSourceContextDefault(action)
    setContextSelections((prev) => ({
      ...prev,
      sources: applyBulkSourceContext(prev.sources, sources ?? [], action),
    }))
  }

  const handleBulkNoteContext = (action: NoteContextDefault) => {
    setNoteContextDefault(action)
    setContextSelections((prev) => ({
      ...prev,
      notes: applyBulkNoteContext(prev.notes, notes ?? [], action),
    }))
  }

  const value = useMemo<NotebookWorkspaceValue>(
    () => ({
      notebookId,
      notebook,
      notebookLoading,
      sources,
      sourcesLoading,
      refetchSources,
      hasNextPage: !!hasNextPage,
      isFetchingNextPage,
      fetchNextPage,
      notes,
      notesLoading,
      contextSelections,
      handleContextModeChange,
      handleBulkSourceContext,
      handleBulkNoteContext,
      chat,
      contextStats,
      dataError: !sources && !notes,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      notebookId,
      notebook,
      notebookLoading,
      sources,
      sourcesLoading,
      hasNextPage,
      isFetchingNextPage,
      notes,
      notesLoading,
      contextSelections,
      chat,
      contextStats,
    ]
  )

  return (
    <NotebookWorkspaceContext.Provider value={value}>
      {children}
    </NotebookWorkspaceContext.Provider>
  )
}
