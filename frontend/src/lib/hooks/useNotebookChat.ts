'use client'

import { useState, useCallback, useEffect, useMemo } from 'react'
import { useQuery, useQueries, useQueryClient } from '@tanstack/react-query'
import { toastApiError } from '@/lib/utils/error-handler'
import { useTranslation } from '@/lib/hooks/use-translation'
import { chatApi } from '@/lib/api/chat'
import { QUERY_KEYS } from '@/lib/api/query-client'
import {
  NotebookChatMessage,
  NotebookChatSession,
  NotebookChatSessionWithMessages,
  SourceListResponse,
  NoteResponse,
  MediaItem
} from '@/lib/types/api'
import { ContextSelections } from '@/lib/types/notebook-context'
import { useBuildNotebookContext } from './useBuildNotebookContext'
import { useNotebookChatSessions } from './useNotebookChatSessions'

// Stable empty fallback for the sessions query. Using a `data: sessions = []`
// destructuring default would mint a NEW array every render while the query is
// loading, churning the identity of `chat.sessions`; effects/memos keyed on it
// (DeepDiveWorkspace's openChat, ChatDock's syncChats) would then re-run every
// render and, via their non-idempotent store writes, spin into an infinite
// update loop on a cold deep-dive load. A module constant keeps the reference
// stable across renders.
const EMPTY_SESSIONS: NotebookChatSession[] = []

interface UseNotebookChatParams {
  notebookId: string
  sources: SourceListResponse[]
  notes: NoteResponse[]
  contextSelections: ContextSelections
  // Sessions whose message streams must be live simultaneously: the dock's
  // active tab plus every popped-out chat panel. The hook fetches each one
  // independently so popped chats render side-by-side.
  visibleSessionIds?: string[]
}

export function useNotebookChat({ notebookId, sources, notes, contextSelections, visibleSessionIds }: UseNotebookChatParams) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  // Per-session in-flight flag (multiple popped chats can send concurrently).
  const [sendingBySession, setSendingBySession] = useState<Record<string, boolean>>({})
  // Pending model override for when user changes model before a session exists.
  const [pendingModelOverride, setPendingModelOverride] = useState<string | null>(null)

  const { buildContext, tokenCount, charCount } = useBuildNotebookContext({
    notebookId,
    sources,
    notes,
    contextSelections,
  })

  const {
    createMainChat,
    createSession,
    updateSession,
    deleteSession,
    createSubChat,
    createSidePanel,
    renameSession,
    setSessionTags,
    promoteToMain,
    setModelOverride,
    setSessionModelOverride,
  } = useNotebookChatSessions({
    notebookId,
    t,
    currentSessionId,
    setCurrentSessionId,
    setPendingModelOverride,
  })

  // Fetch sessions for this notebook.
  const {
    data: sessions = EMPTY_SESSIONS,
    isLoading: loadingSessions,
    refetch: refetchSessions
  } = useQuery({
    queryKey: QUERY_KEYS.notebookChatSessions(notebookId),
    queryFn: () => chatApi.listSessions(notebookId),
    enabled: !!notebookId
  })

  // The set of sessions that need live messages: dock-active + all popped.
  const liveSessionIds = useMemo(() => {
    const set = new Set<string>()
    if (currentSessionId) set.add(currentSessionId)
    for (const id of visibleSessionIds ?? []) if (id) set.add(id)
    return [...set]
  }, [currentSessionId, visibleSessionIds])

  // One message-stream query per live session (multiplexed).
  const sessionQueries = useQueries({
    queries: liveSessionIds.map((id) => ({
      queryKey: QUERY_KEYS.notebookChatSession(id),
      queryFn: () => chatApi.getSession(id),
      enabled: !!notebookId && !!id,
    })),
  })

  // Map each live session id → its fetched session (incl. messages).
  const sessionDataById = useMemo(() => {
    const map: Record<string, NotebookChatSessionWithMessages> = {}
    liveSessionIds.forEach((id, i) => {
      const data = sessionQueries[i]?.data
      if (data) map[id] = data
    })
    return map
  }, [liveSessionIds, sessionQueries])

  const currentSession = currentSessionId ? sessionDataById[currentSessionId] : undefined

  // Read the live messages for any session (empty until its query resolves).
  const getMessages = useCallback(
    (sessionId: string | null): NotebookChatMessage[] =>
      sessionId ? (sessionDataById[sessionId]?.messages ?? []) : [],
    [sessionDataById]
  )
  const getIsSending = useCallback(
    (sessionId: string | null): boolean => (sessionId ? !!sendingBySession[sessionId] : false),
    [sendingBySession]
  )

  // Auto-select most recent session when sessions are loaded.
  useEffect(() => {
    if (sessions.length > 0 && !currentSessionId) {
      setCurrentSessionId(sessions[0].id)
    }
  }, [sessions, currentSessionId])

  // Patch a single session's cached message list (optimistic + reconcile).
  const patchSessionMessages = useCallback(
    (sessionId: string, update: (prev: NotebookChatMessage[]) => NotebookChatMessage[]) => {
      queryClient.setQueryData<NotebookChatSessionWithMessages>(
        QUERY_KEYS.notebookChatSession(sessionId),
        (old) =>
          old
            ? { ...old, messages: update(old.messages ?? []) }
            : ({ messages: update([]) } as NotebookChatSessionWithMessages)
      )
    },
    [queryClient]
  )

  // Send a message to a specific session (multiplexed — popped chats send to
  // their own session independently). Auto-creates a session only when targeting
  // the dock with none selected yet.
  const sendMessageTo = useCallback(
    async (targetSessionId: string | null, message: string, modelOverride?: string, media?: MediaItem[]): Promise<{ ok: boolean }> => {
      let sessionId = targetSessionId

      // Auto-create session if none exists (dock-only path).
      if (!sessionId) {
        try {
          const defaultTitle = message.length > 30 ? `${message.substring(0, 30)}...` : message
          const newSession = await chatApi.createSession({
            notebook_id: notebookId,
            title: defaultTitle,
            model_override: pendingModelOverride ?? undefined
          })
          sessionId = newSession.id
          setCurrentSessionId(sessionId)
          setPendingModelOverride(null)
          queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
        } catch (err: unknown) {
          toastApiError(err, t, 'apiErrors.failedToCreateSession')
          return { ok: false }
        }
      }

      const cachedSession = queryClient.getQueryData<NotebookChatSessionWithMessages>(
        QUERY_KEYS.notebookChatSession(sessionId)
      )

      // Add user message optimistically.
      const userMessage: NotebookChatMessage = {
        id: `temp-${Date.now()}`,
        type: 'human',
        content: message,
        timestamp: new Date().toISOString(),
        media: media && media.length ? media : undefined
      }
      patchSessionMessages(sessionId, (prev) => [...prev, userMessage])
      setSendingBySession((prev) => ({ ...prev, [sessionId!]: true }))

      try {
        const context = await buildContext()
        const response = await chatApi.sendMessage({
          session_id: sessionId,
          message,
          context,
          model_override: modelOverride ?? (cachedSession?.model_override ?? undefined),
          media: media && media.length ? media : undefined
        })
        patchSessionMessages(sessionId, () => response.messages)
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(sessionId) })
        return { ok: true }
      } catch (err: unknown) {
        toastApiError(err, t, 'apiErrors.failedToSendMessage')
        // Remove optimistic message on error. The caller reads { ok: false } to
        // restore the user's draft + staged media (Track A / A2).
        patchSessionMessages(sessionId, (prev) => prev.filter((msg) => !msg.id.startsWith('temp-')))
        return { ok: false }
      } finally {
        setSendingBySession((prev) => ({ ...prev, [sessionId!]: false }))
      }
    },
    [notebookId, pendingModelOverride, buildContext, patchSessionMessages, queryClient, t]
  )

  // Back-compat: send to the dock's active session (auto-creates if none).
  const sendMessage = useCallback(
    (message: string, modelOverride?: string) => sendMessageTo(currentSessionId, message, modelOverride),
    [sendMessageTo, currentSessionId]
  )

  const switchSession = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId)
  }, [])

  // Derived session views: main chats (no parent) + per-main side chat list.
  const mainSessions = useMemo(
    () => sessions.filter((s) => !s.parent_session_id),
    [sessions]
  )
  const sideSessionsOf = useCallback(
    (parentId: string) => sessions.filter((s) => s.parent_session_id === parentId),
    [sessions]
  )

  return {
    sessions,
    currentSession: currentSession || sessions.find((s) => s.id === currentSessionId),
    currentSessionId,
    messages: getMessages(currentSessionId),
    isSending: getIsSending(currentSessionId),
    loadingSessions,
    tokenCount,
    charCount,
    pendingModelOverride,

    getMessages,
    getIsSending,
    sendMessageTo,

    mainSessions,
    sideSessionsOf,

    createSession,
    createMainChat,
    createSubChat,
    createSidePanel,
    updateSession,
    deleteSession,
    renameSession,
    setSessionTags,
    promoteToMain,
    switchSession,
    sendMessage,
    setModelOverride,
    setSessionModelOverride,
    refetchSessions,
  }
}
