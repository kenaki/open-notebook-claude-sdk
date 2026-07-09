'use client'

import type { TFunction } from 'i18next'

import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/hooks/use-translation'
import { cn } from '@/lib/utils'
import type { JobStatus } from '@/lib/stores/jobs-store'

// Status → color-class map extracted from EpisodeCard's StatusBadge
// (frontend/src/components/podcasts/EpisodeCard.tsx ~46-82), generalized to the
// jobs tray's narrower BackgroundJob status union. Kept as its own component so
// podcasts can adopt it later without the tray depending on podcast types.
const getJobStatusMeta = (
  t: TFunction
): Record<JobStatus, { label: string; className: string }> => ({
  new: {
    label: t('jobs.status.new'),
    className: 'bg-sky-100 text-sky-800 border-sky-200',
  },
  running: {
    label: t('jobs.status.running'),
    className: 'bg-amber-100 text-amber-800 border-amber-200',
  },
  completed: {
    label: t('jobs.status.completed'),
    className: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  },
  failed: {
    label: t('jobs.status.failed'),
    className: 'bg-red-100 text-red-800 border-red-200',
  },
  canceled: {
    label: t('jobs.status.canceled'),
    className: 'bg-muted text-muted-foreground border-border',
  },
})

interface JobStatusBadgeProps {
  status: JobStatus
  className?: string
}

export function JobStatusBadge({ status, className }: JobStatusBadgeProps) {
  const { t } = useTranslation()
  const meta = getJobStatusMeta(t)[status]

  return (
    <Badge
      variant="outline"
      className={cn('uppercase tracking-wide text-xs', meta.className, className)}
    >
      {meta.label}
    </Badge>
  )
}
