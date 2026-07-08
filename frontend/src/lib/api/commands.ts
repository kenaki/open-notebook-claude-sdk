import { get } from './client'
import { CommandJobDetail, CommandJobSummary } from '@/lib/types/api'

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
