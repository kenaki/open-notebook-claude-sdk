'use client'

import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { commandsApi } from '@/lib/api/commands'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useTranslation } from '@/lib/hooks/use-translation'
import { BackgroundJob, JobKind, JobStatus, useJobsStore } from '@/lib/stores/jobs-store'
import { CommandJobSummary } from '@/lib/types/api'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import { jobOrigin } from '@/lib/utils/job-origin'

// Grace period before removing a completed/failed job from the store (ms).
// Gives the UI a brief window to show final state before disappearing from tray.
const REMOVE_GRACE_MS = 5_000

// While any active job is running, poll at this interval (ms).
const POLL_INTERVAL_ACTIVE = 4_000

// On mount (first fetch) and for the first few seconds after a new job registers,
// use a snappier interval so the initial status transition feels responsive.
const POLL_INTERVAL_FAST = 1_500

// How long (ms) after a new job registers to use the fast interval.
const FAST_WINDOW_MS = 10_000

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Map a server command `name` + its `args` to our client-side `JobKind`. */
function deriveKind(name: string, args: Record<string, unknown> | null | undefined): JobKind {
  switch (name) {
    case 'chat_completion':
      return (args?.kind as string) === 'source' ? 'source_chat' : 'notebook_chat'
    case 'generate_podcast':
      return 'podcast'
    case 'run_transformation':
      return 'transformation'
    case 'process_source':
    default:
      if (name.startsWith('embed_')) return 'source'
      if (name === 'process_source') return 'source'
      return 'source'
  }
}

/** Cast the server status string to our JobStatus union (defaulting to 'new'). */
function coerceStatus(raw: string | undefined): JobStatus {
  if (raw === 'running' || raw === 'completed' || raw === 'failed') return raw
  return 'new'
}

/** Build a BackgroundJob from a server CommandJobSummary. */
function serverRowToJob(row: CommandJobSummary): BackgroundJob {
  const args = row.args ?? {}
  const kind = deriveKind(row.name, args)

  const sessionId =
    typeof args.session_id === 'string' ? args.session_id : undefined
  const notebookId =
    typeof args.notebook_id === 'string' ? args.notebook_id : undefined
  const targetId =
    typeof args.source_id === 'string'
      ? args.source_id
      : typeof args.target_id === 'string'
        ? args.target_id
        : undefined
  const label =
    typeof args.label === 'string' && args.label.length > 0
      ? args.label
      : row.name

  return {
    jobId: row.job_id,
    kind,
    sessionId,
    notebookId,
    targetId,
    label,
    status: coerceStatus(row.status),
    startedAt: row.created ?? new Date().toISOString(),
    error: row.error_message ?? undefined,
  }
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

/**
 * App-level poller for background jobs.
 *
 * - Polls `GET /commands/jobs?status_filter=active` while any active job exists.
 * - Reconciles server rows into the global Zustand jobs store.
 * - On chat-job completion, invalidates the originating session's TanStack Query
 *   cache so the answer appears in the chat UI.
 * - Persisted in-flight jobs (from before a reload) are reconciled on first poll.
 */
export function useJobsPoller() {
  const queryClient = useQueryClient()
  const router = useRouter()
  const { t } = useTranslation()
  const { jobs, register, update, remove } = useJobsStore()

  // Track when we last saw a new job arrive so we can use the fast-poll window.
  const lastNewJobAt = useRef<number>(0)

  // Track previously seen statuses to detect transitions.
  const prevStatuses = useRef<Map<string, JobStatus>>(new Map())

  // Completion grace-period timers (jobId → timer handle).
  const removeTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const query = useQuery({
    queryKey: ['commands', 'active'] as const,
    queryFn: () => commandsApi.listActive(),
    refetchInterval: (q) => {
      const data = q.state.data as CommandJobSummary[] | undefined

      // Fast window: if a new job just arrived, poll fast for a bit.
      const msSinceNewJob = Date.now() - lastNewJobAt.current
      if (lastNewJobAt.current > 0 && msSinceNewJob < FAST_WINDOW_MS) {
        return POLL_INTERVAL_FAST
      }

      // Active data: poll at standard interval.
      if (data && data.length > 0) return POLL_INTERVAL_ACTIVE

      // Also check the store for persisted in-flight jobs (survive reload).
      const hasPersistedActive = jobs.some(
        (j) => j.status === 'new' || j.status === 'running'
      )
      if (hasPersistedActive) return POLL_INTERVAL_ACTIVE

      // Nothing active — stop polling.
      return false
    },
    meta: { silent: true },
    staleTime: 0,
  })

  useEffect(() => {
    const serverRows = query.data
    if (!serverRows) return

    const serverIds = new Set(serverRows.map((r) => r.job_id))

    // -- Reconcile server rows into the store -----------------------------------
    for (const row of serverRows) {
      const incoming = serverRowToJob(row)
      const existing = jobs.find((j) => j.jobId === row.job_id)

      if (!existing) {
        // Unseen job (server-started podcast/embed, or new chat job) — register.
        register(incoming)
        lastNewJobAt.current = Date.now()
        prevStatuses.current.set(row.job_id, incoming.status)
      } else {
        // Seen job — update status / error if changed.
        const prevStatus = prevStatuses.current.get(row.job_id) ?? existing.status
        if (existing.status !== incoming.status || existing.error !== incoming.error) {
          update(row.job_id, { status: incoming.status, error: incoming.error })
        }

        // Detect transition to terminal state.
        if (
          (prevStatus === 'new' || prevStatus === 'running') &&
          (incoming.status === 'completed' || incoming.status === 'failed')
        ) {
          handleTermination(row.job_id, incoming)
        }

        prevStatuses.current.set(row.job_id, incoming.status)
      }
    }

    // -- Handle persisted jobs that are no longer in the active list ------------
    // A job disappears from the active list when it transitions out of new/running.
    // We need to reflect that in our store (it likely completed while we were away).
    for (const stored of jobs) {
      if (stored.status !== 'new' && stored.status !== 'running') continue
      if (serverIds.has(stored.jobId)) continue

      // Was in-flight, no longer active → treat as completed (most common case).
      // The server may have already moved it to completed; we mark it and invalidate.
      const prevStatus = prevStatuses.current.get(stored.jobId) ?? stored.status
      if (prevStatus === 'new' || prevStatus === 'running') {
        update(stored.jobId, { status: 'completed' })
        prevStatuses.current.set(stored.jobId, 'completed')
        handleTermination(stored.jobId, { ...stored, status: 'completed' })
      }
    }
  }, [query.data]) // eslint-disable-line react-hooks/exhaustive-deps

  /** Handle a job transitioning to completed or failed. */
  function handleTermination(jobId: string, job: BackgroundJob) {
    const isChatJob = job.kind === 'notebook_chat' || job.kind === 'source_chat'

    if (job.status === 'completed') {
      // Invalidate the originating session cache so the answer appears in chat.
      if (isChatJob && job.sessionId) {
        if (job.kind === 'notebook_chat') {
          queryClient.invalidateQueries({
            queryKey: QUERY_KEYS.notebookChatSession(job.sessionId),
          })
        } else {
          // source_chat: needs both targetId (sourceId) and sessionId
          if (job.targetId) {
            queryClient.invalidateQueries({
              queryKey: QUERY_KEYS.sourceChatSession(job.targetId, job.sessionId),
            })
          } else {
            // Fallback: invalidate using just the session key pattern
            queryClient.invalidateQueries({
              queryKey: QUERY_KEYS.notebookChatSession(job.sessionId),
            })
          }
        }
      }

      // Notify only for chat jobs (Q-toast-noise): podcasts/embeds/transforms
      // still update the tray silently, they'd just be noisy if batched.
      if (isChatJob) {
        toast.success(t('jobs.chatReady'), {
          action: {
            label: t('jobs.view'),
            onClick: () => router.push(jobOrigin(job)),
          },
        })
      }
    } else if (job.status === 'failed' && isChatJob) {
      toast.error(getApiErrorMessage(job.error, t, 'jobs.chatFailed'), {
        action: {
          label: t('jobs.view'),
          onClick: () => router.push(jobOrigin(job)),
        },
      })
    }

    // Schedule removal after grace period (allows tray + toast to show final state).
    if (!removeTimers.current.has(jobId)) {
      const timer = setTimeout(() => {
        remove(jobId)
        removeTimers.current.delete(jobId)
        prevStatuses.current.delete(jobId)
      }, REMOVE_GRACE_MS)
      removeTimers.current.set(jobId, timer)
    }
  }

  // Cleanup timers on unmount.
  useEffect(() => {
    return () => {
      for (const timer of removeTimers.current.values()) {
        clearTimeout(timer)
      }
    }
  }, [])

  return query
}
