'use client'

import { useRouter } from 'next/navigation'
import { FileText, Loader2, MessageCircle, MessageSquare, Mic, Shuffle } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { JobStatusBadge } from './JobStatusBadge'
import type { BackgroundJob, JobKind } from '@/lib/stores/jobs-store'

// Minimal inline origin switch (Chunk B2). Refactored into the shared
// `jobOrigin()` helper in Chunk B3 (`frontend/src/lib/utils/job-origin.ts`),
// which the completion/failure toasts also use.
function jobOrigin(job: BackgroundJob): string {
  switch (job.kind) {
    case 'notebook_chat':
      if (job.notebookId && job.sessionId) {
        return `/notebooks/${job.notebookId}/chat/${job.sessionId}`
      }
      return job.notebookId ? `/notebooks/${job.notebookId}` : '/notebooks'
    case 'source_chat':
    case 'source':
    case 'transformation':
      return job.targetId ? `/sources/${job.targetId}` : '/sources'
    case 'podcast':
      return '/podcasts'
    default:
      return '/notebooks'
  }
}

const KIND_ICONS: Record<JobKind, LucideIcon> = {
  notebook_chat: MessageCircle,
  source_chat: MessageSquare,
  podcast: Mic,
  source: FileText,
  transformation: Shuffle,
}

interface JobTrayItemProps {
  job: BackgroundJob
}

export function JobTrayItem({ job }: JobTrayItemProps) {
  const router = useRouter()
  const Icon = KIND_ICONS[job.kind]

  return (
    <button
      type="button"
      onClick={() => router.push(jobOrigin(job))}
      className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent"
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="truncate font-medium text-foreground">{job.label}</p>
        {job.status === 'running' && job.progress?.phase ? (
          <p className="truncate text-xs text-muted-foreground">{job.progress.phase}</p>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {job.status === 'running' ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-600" />
        ) : null}
        <JobStatusBadge status={job.status} />
      </div>
    </button>
  )
}
