'use client'

import { useQuery } from '@tanstack/react-query'

import { commandsApi } from '@/lib/api/commands'
import { QUERY_KEYS } from '@/lib/api/query-client'
import type { CommandJobSummary, JobCounts } from '@/lib/types/api'

/**
 * Job history — the durable record of every background agent run.
 *
 * The job tray is a *live* view: it polls `status_filter=active` and drops each
 * job from the store a minute after it terminates, so a failure you didn't
 * catch within that minute became unreachable even though its row (and its
 * whole `progress.events[]` log) still sits in SurrealDB. This hook reads that
 * history back, which is what makes past agent consoles openable at all.
 *
 * Rows carry no `events[]` — the list endpoint strips them. Opening a row hands
 * its `job_id` to the agent console, which fetches the full log on its own.
 */
export type JobHistoryFilter = 'all' | 'failed' | 'running' | 'new' | 'completed'

// Every filter polls, terminal ones included: while a batch runs, jobs
// terminate every few seconds, so 'completed' and 'failed' are growing sets —
// a board that only polled the active statuses sat frozen on exactly the tabs
// people watch during a batch.
const POLL_INTERVAL_MS = 5_000

export function useJobHistory(filter: JobHistoryFilter) {
  const status = filter === 'all' ? undefined : filter

  return useQuery<CommandJobSummary[]>({
    queryKey: QUERY_KEYS.jobHistory(status),
    queryFn: () => commandsApi.listJobs(status),
    refetchInterval: POLL_INTERVAL_MS,
    staleTime: 2000,
  })
}

/**
 * Table-wide per-status job totals. The list above is capped (200 rows), so
 * `rows.length` saturates at the cap and reads as frozen while jobs churn
 * underneath — the count label uses these real totals instead. Background
 * polling, so failures stay silent (the list query is the loud one).
 */
export function useJobCounts() {
  return useQuery<JobCounts>({
    queryKey: QUERY_KEYS.jobCounts,
    queryFn: () => commandsApi.getJobCounts(),
    refetchInterval: POLL_INTERVAL_MS,
    staleTime: 2000,
    meta: { silent: true },
  })
}
