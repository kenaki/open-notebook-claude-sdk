'use client'

import {
  AlignLeft,
  FileText,
  ListTree,
  Loader2,
  MessageCircle,
  MessageSquare,
  Mic,
  ScanEye,
  ScrollText,
  Sparkles,
  Wand2,
  Waypoints,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { JobStatusBadge } from './JobStatusBadge'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { BackgroundJob, JobKind } from '@/lib/stores/jobs-store'
import { KIND_LABEL_KEY } from '@/lib/stores/jobs-store'
import { useAgentConsoleStore } from '@/lib/stores/agent-console-store'

// One glyph per process type so each is distinguishable at a glance.
export const KIND_ICONS: Record<JobKind, LucideIcon> = {
  notebook_chat: MessageCircle,
  source_chat: MessageSquare,
  podcast: Mic,
  source: FileText,
  embed: Waypoints,
  chapters: ListTree,
  verify: ScanEye,
  summarize: AlignLeft,
  abstract: ScrollText,
  insight: Sparkles,
  illustration: Wand2,
}

interface JobTrayItemProps {
  job: BackgroundJob
}

export function JobTrayItem({ job }: JobTrayItemProps) {
  const { t } = useTranslation()
  const Icon = KIND_ICONS[job.kind]

  // Custom label (chat session name, chapter title) wins; otherwise a human
  // title from the kind. When a custom label takes the title slot, the kind
  // label moves to the subtitle (unless a live phase is already showing) so
  // the row still says WHAT is happening, not just what it's happening to.
  const hasCustomLabel = Boolean(job.label && job.label.trim())
  const title = hasCustomLabel ? job.label : t(KIND_LABEL_KEY[job.kind])
  const phase = job.status === 'running' ? job.progress?.phase : undefined
  const subtitle = phase ?? (hasCustomLabel ? t(KIND_LABEL_KEY[job.kind]) : undefined)

  return (
    <button
      type="button"
      onClick={() => useAgentConsoleStore.getState().open(job.jobId)}
      className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-muted"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
        <Icon className="h-[18px] w-[18px]" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground">{title}</span>
        {(job.command || subtitle) && (
          <span className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted-foreground">
            {job.command && (
              <code className="rounded bg-muted px-1 py-0 font-mono text-[11px] tracking-tight text-muted-foreground">
                {job.command}
              </code>
            )}
            {subtitle && <span className="truncate">{subtitle}</span>}
          </span>
        )}
      </span>
      <span className="flex shrink-0 items-center gap-2">
        {job.status === 'running' && (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-600" />
        )}
        <JobStatusBadge status={job.status} />
      </span>
    </button>
  )
}
