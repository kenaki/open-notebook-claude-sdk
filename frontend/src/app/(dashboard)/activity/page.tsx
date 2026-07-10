'use client'

import { useState } from 'react'
import { Loader2, RefreshCw, Wrench } from 'lucide-react'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { JobStatusBadge } from '@/components/jobs/JobStatusBadge'
import { KIND_ICONS } from '@/components/jobs/JobTrayItem'
import { useJobCounts, useJobHistory, type JobHistoryFilter } from '@/lib/hooks/use-job-history'
import { coerceStatus, deriveKind } from '@/lib/hooks/use-jobs-poller'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useAgentConsoleStore } from '@/lib/stores/agent-console-store'
import { KIND_LABEL_KEY } from '@/lib/stores/jobs-store'
import { formatRelative } from '@/lib/utils/format'
import type { CommandJobSummary } from '@/lib/types/api'

// 'queued' is the human word for the backend's `new` status; the rest map 1:1.
const FILTERS: ReadonlyArray<{ value: JobHistoryFilter; labelKey: string }> = [
  { value: 'all', labelKey: 'activity.filter.all' },
  { value: 'failed', labelKey: 'activity.filter.failed' },
  { value: 'running', labelKey: 'activity.filter.running' },
  { value: 'new', labelKey: 'activity.filter.queued' },
  { value: 'completed', labelKey: 'activity.filter.completed' },
]

function JobHistoryRow({ job, lang }: { job: CommandJobSummary; lang: string }) {
  const { t } = useTranslation()
  const kind = deriveKind(job.name, job.args)
  const status = coerceStatus(job.status)
  const Icon = KIND_ICONS[kind] ?? Wrench

  // Rows written before migration 26 have no `created`; they still open fine,
  // they just can't say when they ran.
  const when = job.created ? formatRelative(job.created, lang) : t('activity.undated')

  return (
    <button
      type="button"
      onClick={() => useAgentConsoleStore.getState().open(job.job_id)}
      className="flex w-full items-start gap-3 rounded-lg border border-transparent px-3 py-2.5 text-left transition-colors hover:border-border hover:bg-muted"
    >
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
        <Icon className="h-[18px] w-[18px]" />
      </span>

      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">
            {t(KIND_LABEL_KEY[kind])}
          </span>
          <code className="shrink-0 rounded bg-muted px-1 font-mono text-[11px] text-muted-foreground">
            {job.name}
          </code>
        </span>

        <span className="mt-0.5 block truncate text-xs text-muted-foreground">{when}</span>

        {status === 'failed' && job.error_message && (
          <span className="mt-1 block truncate font-mono text-[11px] text-destructive">
            {job.error_message}
          </span>
        )}
      </span>

      <span className="flex shrink-0 items-center gap-2">
        {status === 'running' && (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-600" />
        )}
        <JobStatusBadge status={status} />
      </span>
    </button>
  )
}

/**
 * Activity — the durable job history the tray never showed.
 *
 * Rows hand their `job_id` to the shared agent console (mounted once in the
 * dashboard layout), which fetches the full event log itself. The console
 * already tolerates a job that isn't in the live tray store, so a run from days
 * ago replays exactly like a running one, minus the origin link.
 */
export default function ActivityPage() {
  const { t, i18n } = useTranslation()
  const [filter, setFilter] = useState<JobHistoryFilter>('all')
  const { data: jobs, isLoading, isFetching, refetch } = useJobHistory(filter)
  const { data: counts } = useJobCounts()

  const rows = jobs ?? []
  // Real table-wide total for the current filter — the list itself is capped
  // at 200 rows, so `rows.length` would freeze at the cap while jobs churn.
  const total = counts?.[filter] ?? rows.length

  return (
    <AppShell>
      <div className="flex-1 overflow-hidden">
        <div className="flex h-full flex-col p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold text-foreground">{t('activity.title')}</h1>
              <p className="mt-1 text-sm text-muted-foreground">{t('activity.subtitle')}</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              disabled={isFetching}
              aria-label={t('activity.refresh')}
            >
              <RefreshCw className={isFetching ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
              {t('activity.refresh')}
            </Button>
          </div>

          <div className="mt-5 flex items-center justify-between gap-4">
            <Tabs value={filter} onValueChange={(v) => setFilter(v as JobHistoryFilter)}>
              <TabsList>
                {FILTERS.map((f) => (
                  <TabsTrigger key={f.value} value={f.value}>
                    {t(f.labelKey)}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            {!isLoading && (
              <span className="shrink-0 text-xs text-muted-foreground">
                {t('activity.jobCount').replace('{count}', String(total))}
              </span>
            )}
          </div>

          <div className="mt-4 min-h-0 flex-1 rounded-lg border border-border">
            <ScrollArea className="h-full" viewportClassName="p-2">
              {isLoading ? (
                <div className="flex items-center justify-center py-16 text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              ) : rows.length === 0 ? (
                <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
                  {filter === 'all' ? t('activity.empty') : t('activity.emptyFiltered')}
                </div>
              ) : (
                <div className="flex flex-col gap-0.5">
                  {rows.map((job) => (
                    <JobHistoryRow key={job.job_id} job={job} lang={i18n.language} />
                  ))}
                </div>
              )}
            </ScrollArea>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
