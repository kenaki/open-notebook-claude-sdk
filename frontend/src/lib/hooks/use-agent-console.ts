import { useQuery, UseQueryResult } from '@tanstack/react-query'
import { commandsApi } from '@/lib/api/commands'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { CommandJobDetail } from '@/lib/types/api'

// `canceled` is terminal too — the backend flips queued/running rows to it
// (CommandService.cancel_command_job / cancel_source_jobs). Omitting it would
// leave the console polling a dead job at 1s forever.
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'canceled'])

/**
 * Agent console (agent-console B1) — 1s-polling detail query for a single
 * command job's full progress (`progress.events[]` + `args`). Deliberately
 * bypasses jobs-store (coordinator Decision #9): the store only ever holds
 * today's snapshot `progress` (no events), so the console reads this query
 * directly instead. Stops polling once the job reaches a terminal status.
 * `meta: { silent: true }` opts out of the global query-error toast — the
 * console renders its own empty/error state (B2) instead of double-surfacing.
 */
export function useAgentConsole(jobId: string | null): UseQueryResult<CommandJobDetail> {
  return useQuery({
    queryKey: QUERY_KEYS.commandJob(jobId ?? ''),
    queryFn: () => commandsApi.getJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && TERMINAL_STATUSES.has(status) ? false : 1000
    },
    meta: { silent: true },
  })
}
