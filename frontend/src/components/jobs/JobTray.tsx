'use client'

import { useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useJobsStore, type BackgroundJob } from '@/lib/stores/jobs-store'
import { JobTrayItem } from './JobTrayItem'

/**
 * Persistent, always-visible bottom-right indicator for ALL background work —
 * source ingestion, indexing, chaptering, page-proofing, summarizing, insights,
 * podcasts and chat. Reads the store the poller (`use-jobs-poller.ts`) keeps in
 * sync with the server (which returns every running command, not just some).
 *
 * Collapsed it's a compact pill: a live count + spinner while working, a failure
 * indicator when something failed, and a calm "all caught up" state when idle —
 * it never fully disappears. Expanded it groups jobs into Working vs. Recently
 * finished, each row carrying its own icon + label + status.
 */
export function JobTray() {
  const { t } = useTranslation()
  const jobs = useJobsStore((state) => state.jobs)
  const clearFinished = useJobsStore((state) => state.clearFinished)
  const [expanded, setExpanded] = useState(false)

  const working = jobs
    .filter((j) => j.status === 'new' || j.status === 'running')
    // Running before merely-queued so in-progress work sits on top.
    .sort((a, b) => (a.status === 'running' ? 0 : 1) - (b.status === 'running' ? 0 : 1))
  const finished = jobs.filter((j) => j.status === 'completed' || j.status === 'failed')

  const activeCount = working.length
  const runningCount = jobs.filter((j) => j.status === 'running').length
  const failedCount = jobs.filter((j) => j.status === 'failed').length
  const doneCount = jobs.filter((j) => j.status === 'completed').length

  // ─── Collapsed pill (always rendered) ──────────────────────────────────────
  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        aria-label={t('jobs.tray.activeCount').replace('{count}', String(activeCount))}
        className="fixed bottom-4 right-4 z-50 inline-flex h-10 items-center gap-2 rounded-full border border-border bg-card px-3.5 text-sm font-semibold text-foreground shadow-lg transition-colors hover:bg-accent"
      >
        {activeCount > 0 ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin text-amber-600" />
            <span className="tabular-nums">{activeCount}</span>
            {failedCount > 0 && (
              <span className="rounded-full border border-red-200 bg-red-100 px-1.5 text-xs font-semibold text-red-700">
                {failedCount}
              </span>
            )}
          </>
        ) : failedCount > 0 ? (
          <>
            <AlertCircle className="h-4 w-4 text-red-600" />
            <span>{t('jobs.tray.failedCount').replace('{count}', String(failedCount))}</span>
          </>
        ) : doneCount > 0 ? (
          <>
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            <span>{t('jobs.tray.doneCount').replace('{count}', String(doneCount))}</span>
          </>
        ) : (
          <>
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/80 ring-4 ring-emerald-500/15" />
            <span className="font-medium text-muted-foreground">{t('jobs.tray.idle')}</span>
          </>
        )}
      </button>
    )
  }

  // ─── Expanded panel ────────────────────────────────────────────────────────
  return (
    <Card className="fixed bottom-4 right-4 z-50 flex max-h-[70vh] w-80 flex-col gap-0 overflow-hidden py-0 shadow-lg">
      <CardHeader className="gap-0 border-b px-3 py-3 [.border-b]:pb-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm">{t('jobs.tray.title')}</CardTitle>
            {runningCount > 0 && (
              <span className="rounded-full border border-amber-200 bg-amber-100 px-2 py-0.5 text-xs font-semibold tabular-nums text-amber-800">
                {t('jobs.tray.runningCount').replace('{count}', String(runningCount))}
              </span>
            )}
          </div>
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

      <CardContent className="flex-1 space-y-3 overflow-y-auto px-2 py-2">
        {working.length === 0 && finished.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
            <CheckCircle2 className="h-7 w-7 text-emerald-500/70" />
            <p className="text-sm font-medium text-foreground">{t('jobs.tray.idle')}</p>
            <p className="text-xs text-muted-foreground">{t('jobs.tray.empty')}</p>
          </div>
        ) : (
          <>
            {working.length > 0 && (
              <JobGroup label={t('jobs.tray.working')} count={working.length} jobs={working} />
            )}
            {finished.length > 0 && (
              <JobGroup label={t('jobs.tray.finished')} count={finished.length} jobs={finished} />
            )}
          </>
        )}
      </CardContent>

      {finished.length > 0 && (
        <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-muted-foreground">
          <span>{t('jobs.tray.lingerNote')}</span>
          <button
            type="button"
            onClick={clearFinished}
            className="font-medium text-primary hover:underline"
          >
            {t('jobs.tray.clearFinished')}
          </button>
        </div>
      )}
    </Card>
  )
}

function JobGroup({ label, count, jobs }: { label: string; count: number; jobs: BackgroundJob[] }) {
  return (
    <div>
      <div className="flex items-center gap-2 px-2 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        <span>{label}</span>
        <span className="tabular-nums opacity-70">· {count}</span>
      </div>
      <div className="space-y-0.5">
        {jobs.map((job) => (
          <JobTrayItem key={job.jobId} job={job} />
        ))}
      </div>
    </div>
  )
}
