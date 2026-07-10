import { QueryCache, QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import i18n from '@/lib/i18n'
import { getApiErrorMessage } from '@/lib/utils/error-handler'

export const queryClient = new QueryClient({
  // Global surface for *query* failures so they're no longer silent. Mutations are
  // intentionally NOT handled here — they keep their own per-hook onError toasts, so
  // adding a MutationCache here would double-toast. Queries that should stay quiet
  // (prefetch, background polling) opt out via `meta: { silent: true }`.
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.meta?.silent) return
      toast.error(getApiErrorMessage(error, i18n.t.bind(i18n)))
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      gcTime: 10 * 60 * 1000, // 10 minutes
      retry: 2,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 1,
    },
  },
})

export const QUERY_KEYS = {
  notebooks: ['notebooks'] as const,
  notebook: (id: string) => ['notebooks', id] as const,
  notes: (notebookId?: string) => ['notes', notebookId] as const,
  note: (id: string) => ['notes', id] as const,
  sources: (notebookId?: string) => ['sources', notebookId] as const,
  sourcesInfinite: (notebookId: string) => ['sources', 'infinite', notebookId] as const,
  source: (id: string) => ['sources', id] as const,
  settings: ['settings'] as const,
  sourceChatSessions: (sourceId: string) => ['source-chat', sourceId, 'sessions'] as const,
  sourceChatSession: (sourceId: string, sessionId: string) => ['source-chat', sourceId, 'sessions', sessionId] as const,
  notebookChatSessions: (notebookId: string) => ['notebook-chat', notebookId, 'sessions'] as const,
  notebookChatSession: (sessionId: string) => ['notebook-chat', 'sessions', sessionId] as const,
  podcastEpisodes: ['podcasts', 'episodes'] as const,
  podcastEpisode: (episodeId: string) => ['podcasts', 'episodes', episodeId] as const,
  episodeProfiles: ['podcasts', 'episode-profiles'] as const,
  speakerProfiles: ['podcasts', 'speaker-profiles'] as const,
  languages: ['languages'] as const,
  sourceAnnotations: (sourceId: string) => ['sources', sourceId, 'annotations'] as const,
  jobHistory: (status?: string) => ['jobs', 'history', status ?? 'all'] as const,
  jobCounts: ['jobs', 'counts'] as const,
  // Agent console (agent-console B1): detail query for a single command job's
  // full progress (events + args), polled while the console is open.
  commandJob: (jobId: string) => ['commands', 'job', jobId] as const,
}
