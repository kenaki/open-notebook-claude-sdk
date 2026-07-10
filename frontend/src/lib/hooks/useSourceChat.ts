'use client'

import { useState, useCallback, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { toastApiError } from '@/lib/utils/error-handler'
import { useTranslation } from '@/lib/hooks/use-translation'
import { sourceChatApi } from '@/lib/api/source-chat'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useJobsStore } from '@/lib/stores/jobs-store'
import {
  SourceChatSession,
  SourceChatMessage,
  SourceChatSessionWithMessages,
  CreateSourceChatSessionRequest,
  UpdateSourceChatSessionRequest
} from '@/lib/types/api'

export function useSourceChat(sourceId: string) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  // The user asked for a fresh chat but hasn't sent the first message yet. No
  // session row exists yet — `sendMessage`'s auto-create makes one, titled from
  // that message. This flag only exists to hold `currentSessionId` at null: the
  // auto-select effect below would otherwise snap straight back to the most
  // recent session on the very next render.
  const [pendingNewSession, setPendingNewSession] = useState(false)
  // Per-session in-flight flag for the brief submit round-trip (before the job
  // is registered in the store). After registration, isStreaming derives from
  // useJobsStore — no stale local state.
  const [sendingBySession, setSendingBySession] = useState<Record<string, boolean>>({})
  // Subscribe to all jobs so isStreaming re-derives on any status change.
  const storeJobs = useJobsStore((s) => s.jobs)

  // Fetch sessions
  const { data: sessions = [], isLoading: loadingSessions, refetch: refetchSessions } = useQuery<SourceChatSession[]>({
    queryKey: QUERY_KEYS.sourceChatSessions(sourceId),
    queryFn: () => sourceChatApi.listSessions(sourceId),
    enabled: !!sourceId
  })

  // Fetch current session with messages (cache-backed; Track-B poller invalidates
  // this key on job completion to replace the pending placeholder).
  const { data: currentSession } = useQuery<SourceChatSessionWithMessages>({
    queryKey: QUERY_KEYS.sourceChatSession(sourceId, currentSessionId!),
    queryFn: () => sourceChatApi.getSession(sourceId, currentSessionId!),
    enabled: !!sourceId && !!currentSessionId
  })

  // Messages and context indicators are derived directly from the cache so they
  // survive navigation (no local useState copy needed after C3).
  const messages: SourceChatMessage[] = currentSession?.messages ?? []
  const contextIndicators = currentSession?.context_indicators ?? null

  // True while the 202 submit is in-flight OR while the *chat* job for this
  // session is active (new/running). Scoped to kind === 'source_chat' so the
  // fire-and-forget study-memory mirror job (mirror_chat_exchange), which shares
  // this session_id, doesn't keep the "Generating…" spinner spinning after the
  // answer has already rendered.
  const isStreaming = currentSessionId
    ? (!!sendingBySession[currentSessionId] ||
       storeJobs.some(
         (j) =>
           j.sessionId === currentSessionId &&
           j.kind === 'source_chat' &&
           (j.status === 'new' || j.status === 'running')
       ))
    : false

  // Auto-select most recent session when sessions are loaded, unless the user
  // deliberately asked for a new one (then null means "new", not "none yet").
  useEffect(() => {
    if (sessions.length > 0 && !currentSessionId && !pendingNewSession) {
      // Find most recent session (sessions are sorted by created date desc from API)
      const mostRecentSession = sessions[0]
      setCurrentSessionId(mostRecentSession.id)
    }
  }, [sessions, currentSessionId, pendingNewSession])

  // Patch a single session's cached message list (optimistic updates + placeholder).
  const patchSourceSessionMessages = useCallback(
    (sessionId: string, update: (prev: SourceChatMessage[]) => SourceChatMessage[]) => {
      queryClient.setQueryData<SourceChatSessionWithMessages>(
        QUERY_KEYS.sourceChatSession(sourceId, sessionId),
        (old) =>
          old
            ? { ...old, messages: update(old.messages ?? []) }
            : ({ messages: update([]) } as SourceChatSessionWithMessages)
      )
    },
    [queryClient, sourceId]
  )

  // Create session mutation
  const createSessionMutation = useMutation({
    mutationFn: (data: Omit<CreateSourceChatSessionRequest, 'source_id'>) =>
      sourceChatApi.createSession(sourceId, data),
    onSuccess: (newSession) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sourceChatSessions(sourceId) })
      setCurrentSessionId(newSession.id)
      setPendingNewSession(false)
      toast.success(t('chat.sessionCreated'))
    },
    onError: (err: unknown) => {
      toastApiError(err, t, 'apiErrors.failedToCreateSession')
    }
  })

  // Update session mutation
  const updateSessionMutation = useMutation({
    mutationFn: ({ sessionId, data }: { sessionId: string, data: UpdateSourceChatSessionRequest }) =>
      sourceChatApi.updateSession(sourceId, sessionId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sourceChatSessions(sourceId) })
      if (currentSessionId) {
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sourceChatSession(sourceId, currentSessionId) })
      }
      toast.success(t('chat.sessionUpdated'))
    },
    onError: (err: unknown) => {
      toastApiError(err, t, 'apiErrors.failedToUpdateSession')
    }
  })

  // Delete session mutation
  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) =>
      sourceChatApi.deleteSession(sourceId, sessionId),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sourceChatSessions(sourceId) })
      if (currentSessionId === deletedId) {
        setCurrentSessionId(null)
      }
      toast.success(t('chat.sessionDeleted'))
    },
    onError: (err: unknown) => {
      toastApiError(err, t, 'apiErrors.failedToDeleteSession')
    }
  })

  // Send message — submits to the background worker (202), inserts optimistic
  // user message + pending assistant placeholder into the TanStack cache.
  // The Track-B poller delivers the answer by invalidating sourceChatSession.
  const sendMessage = useCallback(async (
    message: string,
    modelOverride?: string,
    // D8: structured annotation references (highlight ids the user is asking
    // about). Resolved server-side into the AI context; the resolved refs come
    // back on the human message as `annotation_refs` (rendered as pills).
    options?: { annotationIds?: string[] }
  ): Promise<{ ok: boolean }> => {
    let sessionId = currentSessionId

    // Auto-create session if none exists
    if (!sessionId) {
      try {
        const defaultTitle = message.length > 30 ? `${message.substring(0, 30)}...` : message
        const newSession = await sourceChatApi.createSession(sourceId, { title: defaultTitle })
        sessionId = newSession.id
        setCurrentSessionId(sessionId)
        setPendingNewSession(false)
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sourceChatSessions(sourceId) })
      } catch (err: unknown) {
        toastApiError(err, t, 'apiErrors.failedToCreateSession')
        return { ok: false }
      }
    }

    // Add user message optimistically to the cache
    const userMessage: SourceChatMessage = {
      id: `temp-${Date.now()}`,
      type: 'human',
      content: message,
      timestamp: new Date().toISOString()
    }
    patchSourceSessionMessages(sessionId, (prev) => [...prev, userMessage])
    setSendingBySession((prev) => ({ ...prev, [sessionId!]: true }))

    try {
      // Submit to the background worker (202). The response carries the job_id;
      // the answer arrives later via the Track-B poller invalidating this session.
      const { job_id } = await sourceChatApi.sendMessage(sourceId, sessionId, {
        message,
        model_override: modelOverride,
        annotation_ids: options?.annotationIds,
      })

      // Register in the global jobs store so isStreaming + the tray track this.
      useJobsStore.getState().register({
        jobId: job_id,
        kind: 'source_chat',
        sessionId,
        targetId: sourceId,
        label: message.slice(0, 60),
        status: 'new',
        startedAt: new Date().toISOString(),
      })

      // Insert a pending assistant placeholder into the cache. The poller (Track B)
      // replaces it by invalidating the session query on job completion.
      patchSourceSessionMessages(sessionId, (prev) => [
        ...prev,
        {
          id: `pending-${job_id}`,
          type: 'ai' as const,
          content: '',
          pending: true,
          timestamp: new Date().toISOString(),
        },
      ])

      return { ok: true }
    } catch (err: unknown) {
      toastApiError(err, t, 'apiErrors.failedToSendMessage')
      // Submission failed: strip the optimistic user message so the caller can
      // restore the draft ({ok:false} contract mirrors C2 notebook-chat pattern).
      patchSourceSessionMessages(sessionId, (prev) =>
        prev.filter((msg) => !msg.id.startsWith('temp-'))
      )
      return { ok: false }
    } finally {
      // Clear the brief submit-round-trip flag; store job status takes over.
      setSendingBySession((prev) => ({ ...prev, [sessionId!]: false }))
    }
  }, [sourceId, currentSessionId, patchSourceSessionMessages, queryClient, t])

  // Switch session
  const switchSession = useCallback((sessionId: string) => {
    setPendingNewSession(false)
    setCurrentSessionId(sessionId)
  }, [])

  /**
   * Target a fresh chat without creating an empty session row. The next
   * `sendMessage` auto-creates one and titles it from that message, so a user
   * who changes their mind leaves no debris behind. Deselecting is also what
   * empties the message list, which is how the panel shows it's a new chat.
   */
  const startNewSession = useCallback(() => {
    setPendingNewSession(true)
    setCurrentSessionId(null)
  }, [])

  // Create session
  const createSession = useCallback((data: Omit<CreateSourceChatSessionRequest, 'source_id'>) => {
    return createSessionMutation.mutate(data)
  }, [createSessionMutation])

  // Update session
  const updateSession = useCallback((sessionId: string, data: UpdateSourceChatSessionRequest) => {
    return updateSessionMutation.mutate({ sessionId, data })
  }, [updateSessionMutation])

  // Delete session
  const deleteSession = useCallback((sessionId: string) => {
    return deleteSessionMutation.mutate(sessionId)
  }, [deleteSessionMutation])

  return {
    // State
    sessions,
    currentSession: sessions.find(s => s.id === currentSessionId),
    currentSessionId,
    messages,
    isStreaming,
    contextIndicators,
    loadingSessions,
    pendingNewSession,

    // Actions
    createSession,
    updateSession,
    deleteSession,
    switchSession,
    startNewSession,
    sendMessage,
    refetchSessions
  }
}
