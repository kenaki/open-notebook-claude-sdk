import { get } from './client'
import { CommandJobSummary } from '@/lib/types/api'

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
   * (e.g. "command:abc123" as returned by listActive / submit).
   */
  getJob: async (id: string): Promise<CommandJobSummary> => {
    return get<CommandJobSummary>(`/commands/jobs/${encodeURIComponent(id)}`)
  },
}

export default commandsApi
