'use client'

import { useState } from 'react'
import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useJobsStore } from '@/lib/stores/jobs-store'
import { JobTrayItem } from './JobTrayItem'

/**
 * Persistent bottom-corner tray aggregating ALL local-model background work
 * (notebook/source chat, podcasts, source processing/embeddings, transformations).
 * Reads the store the poller (`use-jobs-poller.ts`) keeps in sync with the server.
 * Hidden entirely when there are no tracked jobs; otherwise a collapsed pill
 * (count + spinner while any job is active) expands to the full list.
 */
export function JobTray() {
  const { t } = useTranslation()
  const jobs = useJobsStore((state) => state.jobs)
  const [expanded, setExpanded] = useState(false)

  if (jobs.length === 0) {
    return null
  }

  const activeCount = jobs.filter(
    (job) => job.status === 'new' || job.status === 'running'
  ).length

  if (!expanded) {
    return (
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={() => setExpanded(true)}
        className="fixed bottom-4 right-4 z-50 gap-2 rounded-full pr-4 shadow-lg"
        aria-label={t('jobs.tray.activeCount').replace('{count}', String(jobs.length))}
      >
        {activeCount > 0 ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        <span className="font-semibold">{jobs.length}</span>
      </Button>
    )
  }

  return (
    <Card className="fixed bottom-4 right-4 z-50 w-80 max-h-[60vh] gap-2 py-3 shadow-lg">
      <CardHeader className="px-3 pb-0">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">{t('jobs.tray.title')}</CardTitle>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2"
            onClick={() => setExpanded(false)}
          >
            {t('common.close')}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="max-h-[50vh] space-y-1 overflow-y-auto px-3">
        {jobs.map((job) => (
          <JobTrayItem key={job.jobId} job={job} />
        ))}
      </CardContent>
    </Card>
  )
}
