import { get } from './client'
import { CommandJobDetail, CommandJobSummary, JobCounts } from '@/lib/types/api'

export const commandsApi = {
  /**
   * Fetch all active (new + running) jobs.
   * Used by the job-tray poller (Track B) to populate the tray.
   */
  listActive: async (limit = 100): Promise<CommandJobSummary[]> => {
    return get<CommandJobSummary[]>(`/commands/jobs`, {
      params: { status_filter: 'active', limit },
    })
  },

  /**
   * Fetch job history — every command row the database still holds, newest
   * first. The tray only ever asks for `active` jobs and forgets each one a
   * minute after it finishes; this is the endpoint that reaches the rest.
   * `status` matches a single status exactly ('failed' | 'completed' |
   * 'running' | 'new' | 'canceled'); omit it for all jobs.
   */
  listJobs: async (status?: string, limit = 200): Promise<CommandJobSummary[]> => {
    return get<CommandJobSummary[]>(`/commands/jobs`, {
      params: status ? { status_filter: status, limit } : { limit },
    })
  },

  /**
   * Per-status job totals for the whole command table. The list endpoints are
   * capped, so `rows.length` can't tell the activity board how many jobs truly
   * match a filter — this can.
   */
  getJobCounts: async (): Promise<JobCounts> => {
    return get<JobCounts>(`/commands/jobs/counts`)
  },

  /**
   * Fetch a single job by its full SurrealDB record id
   * (e.g. "command:abc123" as returned by listActive / submit). Returns the
   * detail shape (agent-console B1) — full `progress.events[]` + `args` — the
   * job tray poller ignores the extra fields; the agent console consumes them.
   */
  getJob: async (id: string): Promise<CommandJobDetail> => {
    return get<CommandJobDetail>(`/commands/jobs/${encodeURIComponent(id)}`)
  },
}

export default commandsApi
