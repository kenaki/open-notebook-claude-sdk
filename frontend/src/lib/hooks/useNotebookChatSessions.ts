'use client'

import { useCallback } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { toastApiError } from '@/lib/utils/error-handler'
import { chatApi } from '@/lib/api/chat'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { getSideChatModel } from '@/lib/stores/chat-defaults-store'
import type {
  CreateNotebookChatSessionRequest,
  NotebookChatSession,
  NotebookChatSessionWithMessages,
  UpdateNotebookChatSessionRequest,
} from '@/lib/types/api'

// Create-session payload plus an internal optimistic marker. `_tempId`, when
// present, drives the optimistic temp-card insert/reconcile; it is stripped
// before hitting the API.
type CreateSessionVars = CreateNotebookChatSessionRequest & { _tempId?: string }

// All session CRUD mutations + the action callbacks that wrap them.
// Called by useNotebookChat, which passes the pieces of state the mutations
// need to touch (currentSessionId, setCurrentSessionId, setPendingModelOverride).
export function useNotebookChatSessions({
  notebookId,
  t,
  currentSessionId,
  setCurrentSessionId,
  setPendingModelOverride,
}: {
  notebookId: string
  t: (key: string) => string
  currentSessionId: string | null
  setCurrentSessionId: (id: string | null) => void
  setPendingModelOverride: (model: string | null) => void
}) {
  const queryClient = useQueryClient()

  // Optimistic main-chat creation (Track A / A1). When called with a `_tempId`
  // we insert a temp card into the session list AND seed its detail cache so the
  // Deep-Dive dock renders an empty chat instantly — the seeded data is fresh
  // under the 5-min staleTime, so no 404 fetch fires against the not-yet-real id.
  // On success we swap the temp card for the authoritative session; on failure we
  // roll the card back + toast.
  const createSessionMutation = useMutation({
    mutationFn: (vars: CreateSessionVars) => {
      const data: CreateSessionVars = { ...vars }
      delete data._tempId
      return chatApi.createSession(data)
    },
    onMutate: async (vars: CreateSessionVars) => {
      const tempId = vars._tempId
      if (!tempId) return
      await queryClient.cancelQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
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
        queryClient.setQueryData<NotebookChatSession[]>(
          QUERY_KEYS.notebookChatSessions(notebookId),
          (old = []) => old.map((s) => (s.id === ctx.tempId ? newSession : s))
        )
        queryClient.setQueryData<NotebookChatSessionWithMessages>(
          QUERY_KEYS.notebookChatSession(newSession.id),
          (old) => old ?? { ...newSession, messages: [] }
        )
      }
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
    },
    onError: (err: unknown, _vars, ctx) => {
      if (ctx?.previous !== undefined) {
        queryClient.setQueryData(QUERY_KEYS.notebookChatSessions(notebookId), ctx.previous)
      }
      if (ctx?.tempId) {
        queryClient.removeQueries({ queryKey: QUERY_KEYS.notebookChatSession(ctx.tempId) })
      }
      toastApiError(err, t, 'apiErrors.failedToCreateSession')
    },
  })

  const updateSessionMutation = useMutation({
    mutationFn: ({ sessionId, data }: { sessionId: string; data: UpdateNotebookChatSessionRequest }) =>
      chatApi.updateSession(sessionId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(currentSessionId!) })
      toast.success(t('chat.sessionUpdated'))
    },
    onError: (err: unknown) => {
      toastApiError(err, t, 'apiErrors.failedToUpdateSession')
    },
  })

  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) => chatApi.deleteSession(sessionId),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
      queryClient.removeQueries({ queryKey: QUERY_KEYS.notebookChatSession(deletedId) })
      if (currentSessionId === deletedId) setCurrentSessionId(null)
      toast.success(t('chat.sessionDeleted'))
    },
    onError: (err: unknown) => {
      toastApiError(err, t, 'apiErrors.failedToDeleteSession')
    },
  })

  // Optimistic main-chat spawn. Returns the temp id synchronously plus a promise
  // resolving to the real session (or null on error). The gallery navigates to
  // `tempId` immediately, then router.replace()s to the real id once it lands.
  const createMainChat = useCallback(
    (title?: string) => {
      const tempId = `temp-session-${Date.now()}`
      const promise = createSessionMutation
        .mutateAsync({ notebook_id: notebookId, title, _tempId: tempId })
        .catch(() => null)
      return { tempId, promise }
    },
    [createSessionMutation, notebookId]
  )

  // Back-compat await-the-real-session wrapper: ChatDock needs the authoritative
  // session, not the temp card, before it sends the first message.
  const createSession = useCallback(
    (title?: string) => createMainChat(title).promise,
    [createMainChat]
  )

  const updateSession = useCallback(
    (sessionId: string, data: UpdateNotebookChatSessionRequest) =>
      updateSessionMutation.mutate({ sessionId, data }),
    [updateSessionMutation]
  )

  const deleteSession = useCallback(
    (sessionId: string) => deleteSessionMutation.mutate(sessionId),
    [deleteSessionMutation]
  )

  // Spin a sub-chat off a highlighted passage. Creates a session carrying
  // `parent_session_id` + `quote`; title defaults to the truncated quote.
  const createSubChat = useCallback(
    async (parentId: string, quote: string, title?: string) => {
      const trimmed = quote.trim()
      const derivedTitle = title ?? (trimmed.length > 26 ? `${trimmed.slice(0, 26)}…` : trimmed)
      try {
        const sideModel = getSideChatModel(notebookId)
        const newSession = await chatApi.createSession({
          notebook_id: notebookId,
          title: derivedTitle,
          parent_session_id: parentId,
          quote: trimmed,
          model_override: sideModel ?? undefined,
        })
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
        return newSession
      } catch (err: unknown) {
        toastApiError(err, t, 'apiErrors.failedToCreateSession')
        return null
      }
    },
    [notebookId, queryClient, t]
  )

  // Spawn a standalone side chat that opens directly as a popped panel.
  const createSidePanel = useCallback(
    async (title?: string) => {
      try {
        const sideModel = getSideChatModel(notebookId)
        const newSession = await chatApi.createSession({
          notebook_id: notebookId,
          title,
          model_override: sideModel ?? undefined,
        })
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
        return newSession
      } catch (err: unknown) {
        toastApiError(err, t, 'apiErrors.failedToCreateSession')
        return null
      }
    },
    [notebookId, queryClient, t]
  )

  // Silent rename — skips the "Session updated" toast the mutation fires.
  const renameSession = useCallback(
    async (sessionId: string, title: string) => {
      await chatApi.updateSession(sessionId, { title })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(sessionId) })
    },
    [notebookId, queryClient]
  )

  // Silent tag update — refreshes the session list so the gallery re-derives groups.
  const setSessionTags = useCallback(
    async (sessionId: string, tags: string[]) => {
      try {
        await chatApi.updateSession(sessionId, { tags })
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(sessionId) })
      } catch (err: unknown) {
        toastApiError(err, t, 'apiErrors.failedToUpdateSession')
      }
    },
    [notebookId, queryClient, t]
  )

  // Promote a side chat to main by clearing parent_session_id + quote.
  const promoteToMain = useCallback(
    async (sessionId: string) => {
      try {
        await chatApi.updateSession(sessionId, { parent_session_id: null, quote: null })
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(sessionId) })
      } catch (err: unknown) {
        toastApiError(err, t, 'apiErrors.failedToUpdateSession')
      }
    },
    [notebookId, queryClient, t]
  )

  // Set model override — handles both existing sessions and the pending state
  // (no session yet, override stored until session is auto-created on first send).
  const setModelOverride = useCallback(
    (model: string | null) => {
      if (currentSessionId) {
        updateSessionMutation.mutate({ sessionId: currentSessionId, data: { model_override: model } })
      } else {
        setPendingModelOverride(model)
      }
    },
    [currentSessionId, updateSessionMutation, setPendingModelOverride]
  )

  // Silent per-session model override (popped chat panels each target their own
  // session). Mirrors renameSession to skip the toast + active-session invalidation.
  const setSessionModelOverride = useCallback(
    async (sessionId: string, model: string | null) => {
      try {
        await chatApi.updateSession(sessionId, { model_override: model })
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSessions(notebookId) })
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebookChatSession(sessionId) })
      } catch (err: unknown) {
        toastApiError(err, t, 'apiErrors.failedToUpdateSession')
      }
    },
    [notebookId, queryClient, t]
  )

  return {
    createSessionMutation,
    updateSessionMutation,
    deleteSessionMutation,
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
  }
}
