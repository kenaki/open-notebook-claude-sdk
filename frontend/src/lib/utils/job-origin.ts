import type { BackgroundJob } from '@/lib/stores/jobs-store'

/**
 * Resolve the page a background job's result should be viewed on. Shared by
 * `JobTrayItem` (click-to-origin) and `use-jobs-poller.ts`'s completion/failure
 * toast "View" action, so both stay consistent as job kinds evolve.
 */
export function jobOrigin(job: BackgroundJob): string {
  switch (job.kind) {
    case 'notebook_chat':
      if (job.notebookId && job.sessionId) {
        return `/notebooks/${job.notebookId}/chat/${job.sessionId}`
      }
      return job.notebookId ? `/notebooks/${job.notebookId}` : '/notebooks'

    // All source-bound work (chat, ingestion, indexing, chaptering, proofing,
    // summarizing, abstract, insights) opens the source it targets.
    case 'source_chat':
    case 'source':
    case 'embed':
    case 'chapters':
    case 'verify':
    case 'summarize':
    case 'abstract':
    case 'insight':
      return job.targetId ? `/sources/${job.targetId}` : '/sources'

    case 'podcast':
      return '/podcasts'

    default:
      return '/notebooks'
  }
}

export default jobOrigin
