'use client'

import { useState, useCallback, useEffect, useMemo } from 'react'
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import { useTranslation } from '@/lib/hooks/use-translation'
import { chatApi } from '@/lib/api/chat'
import { QUERY_KEYS } from '@/lib/api/query-client'
import {
  NotebookChatMessage,
  NotebookChatSessionWithMessages,
  CreateNotebookChatSessionRequest,
  UpdateNotebookChatSessionRequest,
  SourceListResponse,
  NoteResponse,
  MediaItem
} from '@/lib/types/api'
import { ContextSelections } from '@/app/(dashboard)/notebooks/[id]/page'

interface UseNotebookChatParams {
  notebookId: string
  sources: SourceListResponse[]
  notes: NoteResponse[]
  contextSelections: ContextSelections
  // Sessions whose message streams must be live simultaneously: the dock's
  // active tab plus every popped-out chat panel (Plan C / Chunk 8). The hook
  // fetches each one independently so popped chats render side-by-side. The
  // current dock session is always included implicitly.
  visibleSessionIds?: string[]
}

export function useNotebookChat({ notebookId, sources, notes, contextSelections, visibleSessionIds }: UseNotebookChatParams) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  // Per-session in-flight flag (multiple popped chats can send concurrently).
  const [sendingBySession, setSendingBySession] = useState<Record<string, boolean>>({})
  const [tokenCount, setTokenCount] = useState<number>(0)
  const [charCount, setCharCount] = useState<number>(0)
  // Pending model override for when user changes model before a session exists
  const [pendingModelOverride, setPendingModelOverride] = useState<string | null>(null)

  // Fetch sessions for this notebook
  const {
    data: sessions = [],
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

  // One message-stream query per live session (multiplexed — Chunk 8).
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

  // Auto-select most recent session when sessions are loaded
  useEffect(() => {
    if (sessions.length > 0 && !currentSessionId) {
      // Sessions are sorted by created date desc from API
      const mostRecentSession = sessions[0]
      setCurrentSessionId(mostRecentSession.id)
    }
  }, [sessions, currentSessionId])

  // Create session mutation
  const createSessionMutation = useMutation({
    mutationFn: (data: CreateNotebookChatSessionRequest) =>
      chatApi.createSession(data),
    onSuccess: (newSession) => {
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId)
      })
      setCurrentSessionId(newSession.id)
      toast.success(t('chat.sessionCreated'))
    },
    onError: (err: unknown) => {
      const error = err as { response?: { data?: { detail?: string } }, message?: string };
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToCreateSession'))
    }
  })

  // Update session mutation
  const updateSessionMutation = useMutation({
    mutationFn: ({ sessionId, data }: {
      sessionId: string
      data: UpdateNotebookChatSessionRequest
    }) => chatApi.updateSession(sessionId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId)
      })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSession(currentSessionId!)
      })
      toast.success(t('chat.sessionUpdated'))
    },
    onError: (err: unknown) => {
      const error = err as { response?: { data?: { detail?: string } }, message?: string };
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToUpdateSession'))
    }
  })

  // Delete session mutation
  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) =>
      chatApi.deleteSession(sessionId),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId)
      })
      queryClient.removeQueries({
        queryKey: QUERY_KEYS.notebookChatSession(deletedId)
      })
      if (currentSessionId === deletedId) {
        setCurrentSessionId(null)
      }
      toast.success(t('chat.sessionDeleted'))
    },
    onError: (err: unknown) => {
      const error = err as { response?: { data?: { detail?: string } }, message?: string };
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToDeleteSession'))
    }
  })

  // Build context from sources and notes based on user selections
  const buildContext = useCallback(async () => {
    // Build context_config mapping IDs to selection modes
    const context_config: { sources: Record<string, string>, notes: Record<string, string> } = {
      sources: {},
      notes: {}
    }

    // Map source selections
    sources.forEach(source => {
      const mode = contextSelections.sources[source.id]
      if (mode === 'insights') {
        context_config.sources[source.id] = 'insights'
      } else if (mode === 'full') {
        context_config.sources[source.id] = 'full content'
      } else {
        context_config.sources[source.id] = 'not in'
      }
    })

    // Map note selections
    notes.forEach(note => {
      const mode = contextSelections.notes[note.id]
      if (mode === 'full') {
        context_config.notes[note.id] = 'full content'
      } else {
        context_config.notes[note.id] = 'not in'
      }
    })

    // Call API to build context with actual content
    const response = await chatApi.buildContext({
      notebook_id: notebookId,
      context_config
    })

    // Store token and char counts
    setTokenCount(response.token_count)
    setCharCount(response.char_count)

    return response.context
  }, [notebookId, sources, notes, contextSelections])

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
  const sendMessageTo = useCallback(async (targetSessionId: string | null, message: string, modelOverride?: string, media?: MediaItem[]) => {
    let sessionId = targetSessionId

    // Auto-create session if none exists (dock-only path)
    if (!sessionId) {
      try {
        const defaultTitle = message.length > 30
          ? `${message.substring(0, 30)}...`
          : message
        const newSession = await chatApi.createSession({
          notebook_id: notebookId,
          title: defaultTitle,
          // Include pending model override when creating session
          model_override: pendingModelOverride ?? undefined
        })
        sessionId = newSession.id
        setCurrentSessionId(sessionId)
        // Clear pending model override now that it's applied to the session
        setPendingModelOverride(null)
        queryClient.invalidateQueries({
          queryKey: QUERY_KEYS.notebookChatSessions(notebookId)
        })
      } catch (err: unknown) {
        const error = err as { response?: { data?: { detail?: string } }, message?: string };
        toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToCreateSession'))
        return
      }
    }

    // Resolve this session's stored model override from cache (if loaded).
    const cachedSession = queryClient.getQueryData<NotebookChatSessionWithMessages>(
      QUERY_KEYS.notebookChatSession(sessionId)
    )

    // Add user message optimistically to this session's cached stream.
    const userMessage: NotebookChatMessage = {
      id: `temp-${Date.now()}`,
      type: 'human',
      content: message,
      timestamp: new Date().toISOString(),
      media: media && media.length ? media : undefined
    }
    patchSessionMessages(sessionId, (prev) => [...prev, userMessage])
    setSendingBySession(prev => ({ ...prev, [sessionId!]: true }))

    try {
      // Build context and send message
      const context = await buildContext()
      const response = await chatApi.sendMessage({
        session_id: sessionId,
        message,
        context,
        model_override: modelOverride ?? (cachedSession?.model_override ?? undefined),
        media: media && media.length ? media : undefined
      })

      // Replace the stream with the authoritative server messages.
      patchSessionMessages(sessionId, () => response.messages)
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSession(sessionId)
      })
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }, message?: string };
      console.error('Error sending message:', error)
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToSendMessage'))
      // Remove optimistic message on error
      patchSessionMessages(sessionId, (prev) => prev.filter(msg => !msg.id.startsWith('temp-')))
    } finally {
      setSendingBySession(prev => ({ ...prev, [sessionId!]: false }))
    }
  }, [
    notebookId,
    pendingModelOverride,
    buildContext,
    patchSessionMessages,
    queryClient,
    t
  ])

  // Back-compat: send to the dock's active session (auto-creates if none).
  const sendMessage = useCallback(
    (message: string, modelOverride?: string) => sendMessageTo(currentSessionId, message, modelOverride),
    [sendMessageTo, currentSessionId]
  )

  // Switch session
  const switchSession = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId)
  }, [])

  // Create session
  const createSession = useCallback((title?: string) => {
    return createSessionMutation.mutate({
      notebook_id: notebookId,
      title
    })
  }, [createSessionMutation, notebookId])

  // Update session
  const updateSession = useCallback((sessionId: string, data: UpdateNotebookChatSessionRequest) => {
    return updateSessionMutation.mutate({
      sessionId,
      data
    })
  }, [updateSessionMutation])

  // Delete session
  const deleteSession = useCallback((sessionId: string) => {
    return deleteSessionMutation.mutate(sessionId)
  }, [deleteSessionMutation])

  // Spin a sub-chat off a highlighted passage (Plan D / Chunk 11). Creates a
  // session carrying `parent_session_id` + `quote`; the title defaults to the
  // truncated quote. Invalidating the session list triggers ChatDock's syncChats,
  // which hydrates the new sub-chat as a popped, anchored panel. Returns the new
  // session (or null on error) so the caller can focus its composer.
  const createSubChat = useCallback(async (parentId: string, quote: string, title?: string) => {
    const trimmed = quote.trim()
    const derivedTitle = title ?? (trimmed.length > 26 ? `${trimmed.slice(0, 26)}…` : trimmed)
    try {
      const newSession = await chatApi.createSession({
        notebook_id: notebookId,
        title: derivedTitle,
        parent_session_id: parentId,
        quote: trimmed,
      })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId),
      })
      return newSession
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }, message?: string }
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToCreateSession'))
      return null
    }
  }, [notebookId, queryClient, t])

  // Silent rename — used by the dock to auto-derive a chat title from its first
  // message without the "Session updated" toast the mutation hook fires.
  const renameSession = useCallback(async (sessionId: string, title: string) => {
    await chatApi.updateSession(sessionId, { title })
    queryClient.invalidateQueries({
      queryKey: QUERY_KEYS.notebookChatSessions(notebookId)
    })
    queryClient.invalidateQueries({
      queryKey: QUERY_KEYS.notebookChatSession(sessionId)
    })
  }, [notebookId, queryClient])

  // Set model override - handles both existing sessions and pending state
  const setModelOverride = useCallback((model: string | null) => {
    if (currentSessionId) {
      // Session exists - update it directly
      updateSessionMutation.mutate({
        sessionId: currentSessionId,
        data: { model_override: model }
      })
    } else {
      // No session yet - store as pending
      setPendingModelOverride(model)
    }
  }, [currentSessionId, updateSessionMutation])

  // Update token/char counts when context selections change
  useEffect(() => {
    const updateContextCounts = async () => {
      try {
        await buildContext()
      } catch (error) {
        console.error('Error updating context counts:', error)
      }
    }
    updateContextCounts()
  }, [buildContext])

  return {
    // State
    sessions,
    currentSession: currentSession || sessions.find(s => s.id === currentSessionId),
    currentSessionId,
    // Back-compat single-session view (the dock's active tab).
    messages: getMessages(currentSessionId),
    isSending: getIsSending(currentSessionId),
    loadingSessions,
    tokenCount,
    charCount,
    pendingModelOverride,

    // Multiplexed per-session accessors (popped chats — Chunk 8).
    getMessages,
    getIsSending,
    sendMessageTo,

    // Actions
    createSession,
    createSubChat,
    updateSession,
    deleteSession,
    renameSession,
    switchSession,
    sendMessage,
    setModelOverride,
    refetchSessions
  }
}
