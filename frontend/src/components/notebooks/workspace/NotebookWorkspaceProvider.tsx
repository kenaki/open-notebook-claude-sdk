'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { notebooksApi } from '@/lib/api/notebooks'
import { QUERY_KEYS } from '@/lib/api/query-client'
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
  // The notebook fetch settled with a genuine 404 (notebook does not exist).
  notebookNotFound: boolean
  // The notebook fetch failed transiently (500/network) — recoverable via retry.
  notebookFetchError: boolean
  refetchNotebook: () => void

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
  // True when the sources or notes fetch genuinely failed (a real query error),
  // NOT merely while data is still loading or for an empty notebook.
  dataError: boolean

  // Notebook-wide chat-gallery tag → color-key map, plus a silent setter that
  // persists a single tag's color onto the notebook.
  tagColors: Record<string, string>
  setTagColor: (tag: string, colorKey: string) => void
  // Rename a tag everywhere: rewrite it on every main chat that carries it and
  // migrate its color-map entry. No-op on empty/unchanged names.
  renameTag: (oldTag: string, newName: string) => void

  // Per-notebook auto-illustrate toggle (chat-foundation F6), default ON. Silent
  // setter mirrors `setTagColor`: optimistic cache write + PUT + invalidate.
  autoIllustrate: boolean
  setAutoIllustrate: (next: boolean) => void
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
  const queryClient = useQueryClient()
  const {
    data: notebook,
    isLoading: notebookLoading,
    isError: notebookIsError,
    error: notebookErrorObj,
    refetch: refetchNotebook,
  } = useNotebook(notebookId)
  // Distinguish a genuine 404 (notebook gone → "not found") from a transient
  // failure (500/network → offer retry). Axios errors carry response.status.
  const notebookStatus = (
    notebookErrorObj as { response?: { status?: number } } | null
  )?.response?.status
  const notebookNotFound = notebookIsError && notebookStatus === 404
  const notebookFetchError = notebookIsError && notebookStatus !== 404
  const {
    sources,
    isLoading: sourcesLoading,
    error: sourcesError,
    refetch: refetchSources,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useNotebookSources(notebookId)
  const { data: notes, isLoading: notesLoading, isError: notesIsError } = useNotes(notebookId)
  // `dataError` means "a fetch genuinely failed," not "data is still undefined."
  // The flat `sources` array is always `[] ` (`?? []`), so the old `!sources &&
  // !notes` derivation was effectively always false — it never fired on real
  // errors and could misfire during normal load. Derive from real query flags:
  // loading → skeleton (B2), empty notebook → empty state, only a true error here.
  const dataError = !!sourcesError || notesIsError

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

  // Tag → color-key map persisted on the notebook.
  const tagColors = useMemo(() => notebook?.chat_tag_colors ?? {}, [notebook])

  // Persist a whole tag→color map (silent, no toast): paint optimistically, PUT
  // it, then refresh the notebook caches so every tag chip re-colors.
  const persistTagColors = useCallback(
    (next: Record<string, string>) => {
      queryClient.setQueryData<NotebookResponse>(QUERY_KEYS.notebook(notebookId), (old) =>
        old ? { ...old, chat_tag_colors: next } : old
      )
      void notebooksApi
        .update(notebookId, { chat_tag_colors: next })
        .then(() => {
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebook(notebookId) })
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
        })
    },
    [notebookId, queryClient]
  )

  const setTagColor = useCallback(
    (tag: string, colorKey: string) => {
      persistTagColors({ ...tagColors, [tag.toLowerCase()]: colorKey })
    },
    [tagColors, persistTagColors]
  )

  // Per-notebook auto-illustrate toggle, default ON when unset (matches the
  // backend's `option<bool> DEFAULT true`).
  const autoIllustrate = notebook?.auto_illustrate ?? true

  // Persist the toggle (silent, no toast): paint optimistically, PUT it, then
  // refresh the notebook caches — mirrors `persistTagColors` above.
  const setAutoIllustrate = useCallback(
    (next: boolean) => {
      queryClient.setQueryData<NotebookResponse>(QUERY_KEYS.notebook(notebookId), (old) =>
        old ? { ...old, auto_illustrate: next } : old
      )
      void notebooksApi
        .update(notebookId, { auto_illustrate: next })
        .then(() => {
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebook(notebookId) })
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
        })
    },
    [notebookId, queryClient]
  )

  // Rename a tag across the whole notebook: rewrite it on every main chat that
  // carries it (de-duping if the new name collides with an existing tag), then
  // migrate its color-map entry. `chat.setSessionTags` persists each session.
  const renameTag = useCallback(
    (oldTag: string, newNameRaw: string) => {
      const newName = newNameRaw.trim()
      const oldLower = oldTag.toLowerCase()
      const newLower = newName.toLowerCase()
      // Allow case-only renames (e.g. "grammar" → "Grammar"); bail only when the
      // name is empty or completely unchanged.
      if (!newName || newName === oldTag) return

      for (const session of chat.mainSessions) {
        const tags = session.tags ?? []
        if (!tags.some((tg) => tg.toLowerCase() === oldLower)) continue
        const nextTags: string[] = []
        for (const tg of tags) {
          const replaced = tg.toLowerCase() === oldLower ? newName : tg
          if (!nextTags.some((x) => x.toLowerCase() === replaced.toLowerCase())) {
            nextTags.push(replaced)
          }
        }
        chat.setSessionTags(session.id, nextTags)
      }

      // Migrate the color when the color-map key actually changes (skip case-only
      // renames, whose lowercased key is unchanged). Keep the new tag's existing
      // color if it already has one, else carry the old tag's color over.
      if (oldLower !== newLower && oldLower in tagColors) {
        const next = { ...tagColors }
        if (!(newLower in next)) next[newLower] = next[oldLower]
        delete next[oldLower]
        persistTagColors(next)
      }
    },
    [chat, tagColors, persistTagColors]
  )

  const value = useMemo<NotebookWorkspaceValue>(
    () => ({
      notebookId,
      notebook,
      notebookLoading,
      notebookNotFound,
      notebookFetchError,
      refetchNotebook,
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
      dataError,
      tagColors,
      setTagColor,
      renameTag,
      autoIllustrate,
      setAutoIllustrate,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      notebookId,
      notebook,
      notebookLoading,
      notebookNotFound,
      notebookFetchError,
      refetchNotebook,
      sources,
      sourcesLoading,
      hasNextPage,
      isFetchingNextPage,
      notes,
      notesLoading,
      contextSelections,
      chat,
      contextStats,
      dataError,
      tagColors,
      setTagColor,
      renameTag,
      autoIllustrate,
      setAutoIllustrate,
    ]
  )

  return (
    <NotebookWorkspaceContext.Provider value={value}>
      {children}
    </NotebookWorkspaceContext.Provider>
  )
}
