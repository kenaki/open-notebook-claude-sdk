'use client'

import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { commandsApi } from '@/lib/api/commands'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useTranslation } from '@/lib/hooks/use-translation'
import { BackgroundJob, JobKind, JobStatus, KIND_LABEL_KEY, useJobsStore } from '@/lib/stores/jobs-store'
import { CommandJobSummary } from '@/lib/types/api'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import { jobOrigin } from '@/lib/utils/job-origin'

// How long a completed/failed job lingers in the tray before it auto-clears (ms).
// Long enough to notice a whole pipeline settle; users can also dismiss sooner
// with the tray's "Clear finished" button.
const REMOVE_GRACE_MS = 60_000

// Kinds whose *completion* is worth an interrupting toast. A single upload fans
// out into hundreds of embed/verify/summarize jobs, so toasting every one of
// those completions would be a storm — they stay visible silently in the tray
// instead. Milestone kinds (chat, podcast, source ready, doc abstract) do toast.
// FAILURES toast for every kind regardless (see handleTermination).
const TOAST_ON_COMPLETE: ReadonlySet<JobKind> = new Set<JobKind>([
  'notebook_chat',
  'source_chat',
  'podcast',
  'source',
  'abstract',
])

// While any active job is running, poll at this interval (ms).
const POLL_INTERVAL_ACTIVE = 4_000

// On mount (first fetch) and for the first few seconds after a new job registers,
// use a snappier interval so the initial status transition feels responsive.
const POLL_INTERVAL_FAST = 1_500

// How long (ms) after a new job registers to use the fast interval.
const FAST_WINDOW_MS = 10_000

// When nothing is active, keep a slow baseline poll (rather than stopping) so
// backend-initiated jobs the frontend never registered — source ingestion and
// its fire-and-forget downstream pipeline (embed / chapter / verify-clean /
// summarize / abstract) — surface in the tray within a few seconds. Without
// this the poller sleeps after going idle and only a client-registered job
// (e.g. chat) could ever wake it, so uploads processed invisibly.
const POLL_INTERVAL_IDLE = 10_000

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Map a server command `name` + its `args` to our client-side `JobKind`. */
function deriveKind(name: string, args: Record<string, unknown> | null | undefined): JobKind {
  switch (name) {
    case 'chat_completion':
      return (args?.kind as string) === 'source' ? 'source_chat' : 'notebook_chat'
    case 'generate_podcast':
      return 'podcast'
    case 'run_transformation':
    case 'create_insight':
      return 'insight'
    case 'build_sections':
    case 'backfill_sections':
      return 'chapters'
    case 'verify_clean_section':
    case 'verify_clean_source':
      return 'verify'
    case 'summarize_section':
      return 'summarize'
    case 'generate_source_abstract':
      return 'abstract'
    case 'process_source':
      return 'source'
    default:
      // embed_source / embed_note / embed_insight / embed_chunk / vectorize_source
      // / rebuild_embeddings / backfill_page_numbers → indexing for search.
      if (name.startsWith('embed_') || name.startsWith('vectorize') || name === 'rebuild_embeddings' || name === 'backfill_page_numbers') {
        return 'embed'
      }
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
  // Custom label only for jobs that pass one (chat sessions). Everything else
  // leaves label empty and the row derives a human title from `kind`
  // (KIND_LABEL_KEY) — the raw command name is preserved separately as metadata.
  const label =
    typeof args.label === 'string' && args.label.length > 0 ? args.label : ''
  // Live phase comes from the job's `progress` column, written by long-running
  // commands (e.g. source ingest → "Parsing PDF with Docling"); fall back to a
  // phase passed in args for any client-registered job. The chat tool loop
  // additionally writes `tool_name`/`tool_input` so the chat UI can render a
  // localized, icon-matched label instead of the raw English `phase` string.
  const phase =
    row.progress && typeof row.progress.phase === 'string'
      ? row.progress.phase
      : typeof args.phase === 'string'
        ? args.phase
        : undefined
  const toolName =
    row.progress && typeof row.progress.tool_name === 'string' ? row.progress.tool_name : undefined
  const toolInput =
    row.progress && row.progress.tool_input && typeof row.progress.tool_input === 'object'
      ? row.progress.tool_input
      : undefined

  return {
    jobId: row.job_id,
    kind,
    sessionId,
    notebookId,
    targetId,
    label,
    command: row.name,
    status: coerceStatus(row.status),
    progress: phase ? { phase, tool_name: toolName, tool_input: toolInput } : undefined,
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

  // Jobs currently being resolved via a single-job lookup (see resolveDisappearedJob),
  // so an overlapping poll tick doesn't fire a second lookup/toast for the same job.
  const resolvingIds = useRef<Set<string>>(new Set())

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

      // Nothing active — keep a slow baseline poll so backend-started jobs
      // (source ingestion + its downstream pipeline) still appear in the tray.
      return POLL_INTERVAL_IDLE
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
        // Seen job — update status / error / live phase if changed.
        const prevStatus = prevStatuses.current.get(row.job_id) ?? existing.status
        if (
          existing.status !== incoming.status ||
          existing.error !== incoming.error ||
          existing.progress?.phase !== incoming.progress?.phase
        ) {
          update(row.job_id, {
            status: incoming.status,
            error: incoming.error,
            progress: incoming.progress,
          })
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
    // A job disappears from the active list when it transitions out of new/running
    // — that includes `failed`, not just `completed`. Look up its real terminal
    // status/error instead of assuming success, so a fast failure (e.g. a
    // provider error) surfaces as a failure toast instead of a false "ready" one.
    for (const stored of jobs) {
      if (stored.status !== 'new' && stored.status !== 'running') continue
      if (serverIds.has(stored.jobId)) continue

      const prevStatus = prevStatuses.current.get(stored.jobId) ?? stored.status
      if (prevStatus !== 'new' && prevStatus !== 'running') continue
      if (resolvingIds.current.has(stored.jobId)) continue

      resolvingIds.current.add(stored.jobId)
      resolveDisappearedJob(stored).finally(() => {
        resolvingIds.current.delete(stored.jobId)
      })
    }
  }, [query.data]) // eslint-disable-line react-hooks/exhaustive-deps

  /**
   * A job vanished from the active-jobs poll. Fetch its real terminal status
   * via the single-job endpoint rather than assuming it completed — a job can
   * just as easily have failed between two poll ticks. Falls back to the old
   * "assume completed" behavior only if the lookup itself can't be resolved
   * (e.g. the job record was purged), so the UI never gets stuck.
   */
  async function resolveDisappearedJob(stored: BackgroundJob) {
    let finalStatus: JobStatus = 'completed'
    let error: string | undefined
    try {
      const row = await commandsApi.getJob(stored.jobId)
      finalStatus = coerceStatus(row.status)
      error = row.error_message ?? undefined
      // Genuinely still active (rare race) — leave it for the next poll tick
      // instead of forcing a terminal state.
      if (finalStatus !== 'completed' && finalStatus !== 'failed') return
    } catch {
      // Lookup failed — fall back to the previous best-effort assumption
      // rather than leaving the job stuck in the tray forever.
    }
    update(stored.jobId, { status: finalStatus, error })
    prevStatuses.current.set(stored.jobId, finalStatus)
    handleTermination(stored.jobId, { ...stored, status: finalStatus, error })
  }

  /** Human title for a job in a toast (custom label, else its kind's label). */
  function jobTitle(job: BackgroundJob): string {
    return job.label && job.label.trim() ? job.label : t(KIND_LABEL_KEY[job.kind])
  }

  /** Handle a job transitioning to completed or failed. */
  function handleTermination(jobId: string, job: BackgroundJob) {
    const isChatJob = job.kind === 'notebook_chat' || job.kind === 'source_chat'
    const viewAction = {
      label: t('jobs.view'),
      onClick: () => router.push(jobOrigin(job)),
    }

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

      // Completion toasts: chat gets its tailored copy; other milestone kinds
      // (TOAST_ON_COMPLETE) get a generic "finished" toast. High-cardinality
      // fan-out jobs (embed/verify/summarize) complete silently in the tray.
      if (isChatJob) {
        toast.success(t('jobs.chatReady'), { action: viewAction })
      } else if (TOAST_ON_COMPLETE.has(job.kind)) {
        toast.success(t('jobs.finishedToast').replace('{job}', jobTitle(job)), {
          action: viewAction,
        })
      }
    } else if (job.status === 'failed') {
      // Every kind's failure is surfaced — failures are rare and worth knowing.
      const message = isChatJob
        ? getApiErrorMessage(job.error, t, 'jobs.chatFailed')
        : t('jobs.failedToast').replace('{job}', jobTitle(job))
      toast.error(message, { action: viewAction })
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
