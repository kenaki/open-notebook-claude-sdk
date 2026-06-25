'use client'

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { toastApiError } from '@/lib/utils/error-handler'
import { useTranslation } from '@/lib/hooks/use-translation'
import { chatApi } from '@/lib/api/chat'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { getSideChatModel } from '@/lib/stores/chat-defaults-store'
import {
  NotebookChatMessage,
  NotebookChatSession,
  NotebookChatSessionWithMessages,
  CreateNotebookChatSessionRequest,
  UpdateNotebookChatSessionRequest,
  SourceListResponse,
  NoteResponse,
  MediaItem
} from '@/lib/types/api'
import { ContextSelections } from '@/lib/types/notebook-context'

// Create-session payload plus an internal optimistic marker. `_tempId`, when
// present, drives the optimistic temp-card insert/reconcile in
// createSessionMutation (Track A / A1); it is stripped before hitting the API.
type CreateSessionVars = CreateNotebookChatSessionRequest & { _tempId?: string }

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

  // Optimistic main-chat creation (Track A / A1). When called with a `_tempId`
  // (the gallery's instant-spawn path) we insert a temp card into the session
  // list AND seed its detail cache so the Deep-Dive dock renders an empty chat
  // instantly — the seeded data is fresh under the 5-min staleTime, so no 404
  // fetch fires against the not-yet-real id. On success we swap the temp card
  // for the authoritative session; on failure we roll the card back + toast.
  const createSessionMutation = useMutation({
    // _tempId is an internal optimistic marker, not part of the API payload.
    mutationFn: (vars: CreateSessionVars) => {
      const data: CreateSessionVars = { ...vars }
      delete data._tempId
      return chatApi.createSession(data)
    },
    onMutate: async (vars: CreateSessionVars) => {
      const tempId = vars._tempId
      if (!tempId) return
      await queryClient.cancelQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId)
      })
      const previous = queryClient.getQueryData<NotebookChatSession[]>(
        QUERY_KEYS.notebookChatSessions(notebookId)
      )
      const now = new Date().toISOString()
      const optimistic: NotebookChatSessionWithMessages = {
        id: tempId,
        notebook_id: notebookId,
        title: vars.title ?? '',
        created: now,
        updated: now,
        message_count: 0,
        model_override: vars.model_override ?? null,
        messages: [],
      }
      queryClient.setQueryData<NotebookChatSession[]>(
        QUERY_KEYS.notebookChatSessions(notebookId),
        (old = []) => [optimistic, ...old]
      )
      queryClient.setQueryData<NotebookChatSessionWithMessages>(
        QUERY_KEYS.notebookChatSession(tempId),
        optimistic
      )
      return { previous, tempId }
    },
    onSuccess: (newSession, _vars, ctx) => {
      if (ctx?.tempId) {
        // Swap the temp card for the authoritative session in the list…
        queryClient.setQueryData<NotebookChatSession[]>(
          QUERY_KEYS.notebookChatSessions(notebookId),
          (old = []) => old.map((s) => (s.id === ctx.tempId ? newSession : s))
        )
        // …and seed its detail cache so the dock has it before any refetch.
        queryClient.setQueryData<NotebookChatSessionWithMessages>(
          QUERY_KEYS.notebookChatSession(newSession.id),
          (old) => old ?? { ...newSession, messages: [] }
        )
      }
      // Reconcile against the server (no longer the source of truth for the card).
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId)
      })
    },
    onError: (err: unknown, _vars, ctx) => {
      if (ctx?.previous !== undefined) {
        queryClient.setQueryData(
          QUERY_KEYS.notebookChatSessions(notebookId),
          ctx.previous
        )
      }
      if (ctx?.tempId) {
        queryClient.removeQueries({
          queryKey: QUERY_KEYS.notebookChatSession(ctx.tempId)
        })
      }
      toastApiError(err, t, 'apiErrors.failedToCreateSession')
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
      toastApiError(err, t, 'apiErrors.failedToUpdateSession')
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
      toastApiError(err, t, 'apiErrors.failedToDeleteSession')
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
  const sendMessageTo = useCallback(async (targetSessionId: string | null, message: string, modelOverride?: string, media?: MediaItem[]): Promise<{ ok: boolean }> => {
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
        toastApiError(err, t, 'apiErrors.failedToCreateSession')
        return { ok: false }
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
      return { ok: true }
    } catch (err: unknown) {
      toastApiError(err, t, 'apiErrors.failedToSendMessage')
      // Remove optimistic message on error. The caller (ChatPanel via the dock)
      // reads { ok: false } to restore the user's draft + staged media (Track A / A2).
      patchSessionMessages(sessionId, (prev) => prev.filter(msg => !msg.id.startsWith('temp-')))
      return { ok: false }
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

  // Optimistic main-chat spawn (Track A / A1). Returns the temp id synchronously
  // plus a promise resolving to the real session (or null on error). The gallery
  // navigates to `tempId` immediately for an instant feel, then router.replace()s
  // to the real id once it lands. onError of the mutation already toasts.
  const createMainChat = useCallback((title?: string) => {
    const tempId = `temp-session-${Date.now()}`
    const promise = createSessionMutation
      .mutateAsync({ notebook_id: notebookId, title, _tempId: tempId })
      .catch(() => null)
    return { tempId, promise }
  }, [createSessionMutation, notebookId])

  // Create a MAIN chat (Sidebar redesign / Chunk 2). Back-compat await-the-real-
  // session wrapper: ChatDock spins a main then sends to its real id, so it needs
  // the authoritative session, not the temp card. Follows the global default
  // model (side-chat defaults are reserved for createSubChat / createSidePanel).
  const createSession = useCallback(
    (title?: string) => createMainChat(title).promise,
    [createMainChat]
  )

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
      // Side chats inherit the notebook's configured side-chat default model
      // (dock header cog). null → omit, so the chat follows the global default.
      const sideModel = getSideChatModel(notebookId)
      const newSession = await chatApi.createSession({
        notebook_id: notebookId,
        title: derivedTitle,
        parent_session_id: parentId,
        quote: trimmed,
        model_override: sideModel ?? undefined,
      })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId),
      })
      return newSession
    } catch (err: unknown) {
      toastApiError(err, t, 'apiErrors.failedToCreateSession')
      return null
    }
  }, [notebookId, queryClient, t])

  // Spawn a standalone side chat that opens directly as a popped panel (the
  // track's "+" button). Like createSubChat but with no parent/quote — it's an
  // empty side conversation. Returns the new session (or null) so the caller can
  // pop it out (popChat) and focus/scroll to it; the title defaults to the
  // caller's "New chat" label so the first-message auto-rename still fires.
  const createSidePanel = useCallback(async (title?: string) => {
    try {
      const sideModel = getSideChatModel(notebookId)
      const newSession = await chatApi.createSession({
        notebook_id: notebookId,
        title,
        model_override: sideModel ?? undefined,
      })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId),
      })
      return newSession
    } catch (err: unknown) {
      toastApiError(err, t, 'apiErrors.failedToCreateSession')
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

  // Silent tag update (gallery grouping). Replaces a session's tags wholesale and
  // refreshes the session list so the gallery's group filter + cards re-derive.
  // Mirrors renameSession: hits the API directly to skip the "Session updated"
  // toast the mutation hook fires.
  const setSessionTags = useCallback(async (sessionId: string, tags: string[]) => {
    try {
      await chatApi.updateSession(sessionId, { tags })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId)
      })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSession(sessionId)
      })
    } catch (err: unknown) {
      toastApiError(err, t, 'apiErrors.failedToUpdateSession')
    }
  }, [notebookId, queryClient, t])

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

  // Silent per-session model override (popped chat panels each target their own
  // session, not the dock's active tab). Mirrors renameSession: hits the API
  // directly to skip the "Session updated" toast and the active-session-scoped
  // invalidation that updateSessionMutation fires, then refreshes the right keys
  // so the new model surfaces in every view of this session.
  const setSessionModelOverride = useCallback(async (sessionId: string, model: string | null) => {
    try {
      await chatApi.updateSession(sessionId, { model_override: model })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId)
      })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSession(sessionId)
      })
    } catch (err: unknown) {
      toastApiError(err, t, 'apiErrors.failedToUpdateSession')
    }
  }, [notebookId, queryClient, t])

  // Promote a side chat to a main chat (Sidebar redesign / Chunk 1). Silent —
  // mirrors renameSession: PUTs parent_session_id/quote = null to clear them, so
  // the session detaches from its parent and surfaces in the sidebar's main list.
  const promoteToMain = useCallback(async (sessionId: string) => {
    try {
      await chatApi.updateSession(sessionId, { parent_session_id: null, quote: null })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSessions(notebookId)
      })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notebookChatSession(sessionId)
      })
    } catch (err: unknown) {
      toastApiError(err, t, 'apiErrors.failedToUpdateSession')
    }
  }, [notebookId, queryClient, t])

  // Derived session views for the sidebar (Sidebar redesign / Chunk 1). Main
  // chats (no parent) drive the sidebar list; sideSessionsOf lists a main's side
  // chats (incl. hidden) for its "side chats (n)" control. Sessions arrive from
  // the API ordered `updated desc`, so these inherit that recency order.
  const mainSessions = useMemo(
    () => sessions.filter((s) => !s.parent_session_id),
    [sessions]
  )
  const sideSessionsOf = useCallback(
    (parentId: string) => sessions.filter((s) => s.parent_session_id === parentId),
    [sessions]
  )

  // Update token/char counts when context selections change.
  // The first run fires immediately so counts populate on mount; rapid
  // source/note toggling after that is debounced (250ms trailing) so a burst
  // of changes collapses into a single POST /chat/context instead of one per
  // toggle. The pending timer is cleared on each input change and on unmount.
  const contextDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const contextCountsPrimedRef = useRef(false)
  useEffect(() => {
    const updateContextCounts = async () => {
      try {
        await buildContext()
      } catch (error) {
        console.error('Error updating context counts:', error)
      }
    }

    if (!contextCountsPrimedRef.current) {
      contextCountsPrimedRef.current = true
      updateContextCounts()
      return
    }

    if (contextDebounceRef.current) {
      clearTimeout(contextDebounceRef.current)
    }
    contextDebounceRef.current = setTimeout(updateContextCounts, 250)

    return () => {
      if (contextDebounceRef.current) {
        clearTimeout(contextDebounceRef.current)
        contextDebounceRef.current = null
      }
    }
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

    // Sidebar redesign (Chunk 1): main/side session views.
    mainSessions,
    sideSessionsOf,

    // Actions
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
    refetchSessions
  }
}
