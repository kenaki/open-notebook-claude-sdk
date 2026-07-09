'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Brain, ExternalLink, Wrench, X } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { describeTool, detailFor } from '@/components/source/chat/ToolUseDisclosure'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useAgentConsole } from '@/lib/hooks/use-agent-console'
import { useAgentConsoleStore } from '@/lib/stores/agent-console-store'
import { KIND_ICONS } from './JobTrayItem'
import { JobStatusBadge } from './JobStatusBadge'
import { KIND_LABEL_KEY, useJobsStore, type JobStatus } from '@/lib/stores/jobs-store'
import { jobOrigin } from '@/lib/utils/job-origin'
import { cn } from '@/lib/utils'
import type { JobEvent } from '@/lib/types/api'

// Server-side cap (coordinator Event contract): `progress.events[]` is capped
// at 200, oldest trimmed first. The client can't tell exactly how many were
// trimmed (no counter on the wire), but it CAN tell the cap was hit — the
// array is sitting at exactly the cap — and surface a one-line notice.
const EVENT_CAP = 200
const KNOWN_STATUSES = new Set<JobStatus>(['new', 'running', 'completed', 'failed'])

// One row per rendered activity item. Consecutive `thinking` events are
// coalesced into a single row (coordinator spec) so a stream of small
// ~2s/~400-char chunks reads as one continuous block of reasoning instead of
// a flickering list of fragments.
type ConsoleRow =
  | { key: string; kind: 'phase'; label: string }
  | { key: string; kind: 'tool_call'; toolName: string; toolInput?: Record<string, unknown> }
  | { key: string; kind: 'tool_result'; toolName: string; preview?: string; isError?: boolean }
  | { key: string; kind: 'thinking'; text: string }
  | { key: string; kind: 'context'; chars?: number; preview?: string }

export function coalesceEvents(events: JobEvent[]): ConsoleRow[] {
  const rows: ConsoleRow[] = []
  events.forEach((event, index) => {
    if (event.type === 'thinking') {
      const prev = rows[rows.length - 1]
      if (prev && prev.kind === 'thinking') {
        prev.text = prev.text ? `${prev.text} ${event.text}` : event.text
        return
      }
      rows.push({ key: `${event.t}-${index}`, kind: 'thinking', text: event.text })
      return
    }
    if (event.type === 'phase') {
      rows.push({ key: `${event.t}-${index}`, kind: 'phase', label: event.label })
    } else if (event.type === 'tool_call') {
      rows.push({
        key: `${event.t}-${index}`,
        kind: 'tool_call',
        toolName: event.tool_name,
        toolInput: event.tool_input,
      })
    } else if (event.type === 'tool_result') {
      rows.push({
        key: `${event.t}-${index}`,
        kind: 'tool_result',
        toolName: event.tool_name,
        preview: event.preview,
        isError: event.is_error,
      })
    } else if (event.type === 'context') {
      rows.push({ key: `${event.t}-${index}`, kind: 'context', chars: event.chars, preview: event.preview })
    }
  })
  return rows
}

function toDisplayString(value: unknown): string | undefined {
  if (value == null) return undefined
  if (typeof value === 'string') return value.trim() ? value : undefined
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return undefined
  }
}

// Renders a status badge even for statuses `JobStatusBadge` doesn't know
// about (e.g. `canceled`, which the backend can set but which isn't part of
// the narrower tray `JobStatus` union) — falls back to a plain badge with the
// raw status text instead of crashing on a missing lookup entry.
function ConsoleStatusBadge({ status }: { status?: string }) {
  if (!status) return null
  if (KNOWN_STATUSES.has(status as JobStatus)) {
    return <JobStatusBadge status={status as JobStatus} />
  }
  return (
    <Badge variant="outline" className="uppercase tracking-wide text-xs">
      {status}
    </Badge>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex flex-1 items-center justify-center py-10 text-center text-sm text-muted-foreground">
      {text}
    </div>
  )
}

function ConsoleRowView({ row, t }: { row: ConsoleRow; t: (key: string) => string }) {
  if (row.kind === 'phase') {
    return (
      <div className="my-1 flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <span className="h-px flex-1 bg-border" />
        {row.label}
        <span className="h-px flex-1 bg-border" />
      </div>
    )
  }

  if (row.kind === 'tool_call') {
    const { Icon, liveKey } = describeTool(row.toolName)
    const detail = row.toolInput ? detailFor(row.toolInput) : null
    return (
      <div className="flex items-start gap-1.5 text-xs leading-snug">
        <Icon className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="min-w-0 flex-1">
          <span className="text-foreground">{t(liveKey)}</span>
          {detail && <span className="ml-1.5 truncate font-mono text-[11px] text-muted-foreground">{detail}</span>}
        </span>
      </div>
    )
  }

  if (row.kind === 'tool_result') {
    const { Icon, key } = describeTool(row.toolName)
    return (
      <div className="flex items-start gap-1.5 text-xs leading-snug">
        <Icon
          className={cn('mt-0.5 h-3.5 w-3.5 flex-shrink-0', row.isError ? 'text-destructive' : 'text-muted-foreground')}
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1">
          <span className={row.isError ? 'text-destructive' : 'text-foreground'}>{t(key)}</span>
          {row.preview && (
            <span className="mt-0.5 block truncate font-mono text-[11px] text-muted-foreground">{row.preview}</span>
          )}
        </span>
      </div>
    )
  }

  if (row.kind === 'thinking') {
    return (
      <div className="rounded-lg border border-border-2 bg-panel-2 px-2.5 py-2">
        <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
          <Brain className="h-3.5 w-3.5" aria-hidden="true" />
          {t('console.thinking')}
        </div>
        <p className="whitespace-pre-wrap text-xs italic text-muted-foreground">{row.text}</p>
      </div>
    )
  }

  // context
  return (
    <div className="text-xs text-muted-foreground">
      <span className="font-medium text-foreground">
        {t('console.chars').replace('{count}', String(row.chars ?? 0))}
      </span>
      {row.preview && <span className="ml-1.5 truncate font-mono text-[11px]">{row.preview}</span>}
    </div>
  )
}

/**
 * Agent console (agent-console B2) — right-anchored slide-over tailing a
 * single command job's full event feed. Opened via `agent-console-store`
 * (job-tray tap, in-chat "view process" — both B3); this component only
 * reads the store, never writes `openJobId` itself except on close.
 *
 * Structure mirrors `UtilityDrawer.tsx` (the only slide-over precedent in the
 * codebase — no `ui/Sheet` exists): a header, then content. Unlike
 * UtilityDrawer's width-collapsing inline panel, this is a fixed overlay, so
 * the "same transition" (duration-300 ease-out, no animation library) is
 * expressed as a transform slide instead of a width collapse.
 */
export function AgentConsole() {
  const { t } = useTranslation()
  const router = useRouter()
  const openJobId = useAgentConsoleStore((s) => s.openJobId)
  const close = useAgentConsoleStore((s) => s.close)
  const job = useJobsStore((s) => s.jobs.find((j) => j.jobId === openJobId))
  const { data: detail } = useAgentConsole(openJobId)

  const [slidIn, setSlidIn] = useState(false)
  const activityWrapRef = useRef<HTMLDivElement | null>(null)
  const atBottomRef = useRef(true)

  useEffect(() => {
    if (!openJobId) {
      setSlidIn(false)
      return
    }
    const raf = requestAnimationFrame(() => setSlidIn(true))
    return () => cancelAnimationFrame(raf)
  }, [openJobId])

  useEffect(() => {
    if (!openJobId) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [openJobId, close])

  const events = useMemo(() => detail?.progress?.events ?? [], [detail])
  const rows = useMemo(() => coalesceEvents(events), [events])
  const isStreaming = detail?.status === 'new' || detail?.status === 'running'
  const isCapped = events.length >= EVENT_CAP

  const contextEvent = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const ev = events[i]
      if (ev.type === 'context') return ev
    }
    return undefined
  }, [events])
  const argsContext = toDisplayString(detail?.args?.context)
  const argsMessage = toDisplayString(detail?.args?.message)
  const hasContext = !!contextEvent || !!argsContext || !!argsMessage

  // Bottom-pinned auto-scroll: keep tailing while the user is at (or near)
  // the bottom; stop the moment they scroll up to read, matching the chat
  // dock's `useChatScrollAnchor` viewport-query idiom.
  useEffect(() => {
    const viewport = activityWrapRef.current?.querySelector<HTMLElement>('[data-slot="scroll-area-viewport"]')
    if (!viewport) return
    const onScroll = () => {
      const distance = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight
      atBottomRef.current = distance < 48
    }
    viewport.addEventListener('scroll', onScroll)
    return () => viewport.removeEventListener('scroll', onScroll)
  }, [openJobId])

  useEffect(() => {
    if (!atBottomRef.current) return
    const viewport = activityWrapRef.current?.querySelector<HTMLElement>('[data-slot="scroll-area-viewport"]')
    if (!viewport) return
    viewport.scrollTop = viewport.scrollHeight
  }, [rows.length])

  if (!openJobId) return null

  const Icon = job ? KIND_ICONS[job.kind] : Wrench
  const title = job?.label?.trim() ? job.label : job ? t(KIND_LABEL_KEY[job.kind]) : (detail?.name ?? '')
  const status = detail?.status ?? job?.status

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/20 transition-opacity duration-300 ease-out"
        onClick={close}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('console.title')}
        className={cn(
          'fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-border bg-card shadow-2xl transition-transform duration-300 ease-out will-change-transform sm:w-[28rem]',
          slidIn ? 'translate-x-0' : 'translate-x-full'
        )}
      >
        <div className="flex flex-shrink-0 items-center gap-2 border-b border-border px-4 py-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
            <Icon className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-foreground">{title}</div>
          </div>
          <ConsoleStatusBadge status={status} />
          {job && (
            <button
              type="button"
              onClick={() => {
                close()
                router.push(jobOrigin(job))
              }}
              className="flex items-center gap-1 rounded px-1.5 py-1 text-xs font-medium text-primary hover:underline"
            >
              {t('console.goToOrigin')}
              <ExternalLink className="h-3.5 w-3.5" />
            </button>
          )}
          <button
            type="button"
            onClick={close}
            title={t('common.close')}
            aria-label={t('common.close')}
            className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <Tabs defaultValue="activity" className="min-h-0 flex-1 gap-0">
          <TabsList className="mx-4 mt-3 self-start">
            <TabsTrigger value="activity">{t('console.activity')}</TabsTrigger>
            <TabsTrigger value="context">{t('console.context')}</TabsTrigger>
          </TabsList>

          <TabsContent value="activity" className="mt-3 flex min-h-0 flex-1 flex-col">
            <div ref={activityWrapRef} className="min-h-0 flex-1">
              <ScrollArea className="h-full" viewportClassName="px-4 pb-3">
                {rows.length === 0 && (
                  <EmptyState text={t('console.empty')} />
                )}
                {(rows.length > 0 || isStreaming) && (
                  <div className="flex flex-col gap-2">
                    {isCapped && (
                      <div className="rounded border border-border-2 bg-panel-2 px-2 py-1 text-[11px] text-muted-foreground">
                        {t('console.truncated')}
                      </div>
                    )}
                    {rows.map((row) => (
                      <ConsoleRowView key={row.key} row={row} t={t} />
                    ))}
                    {isStreaming && (
                      <div className="flex items-center gap-1.5 py-1 text-[11px] text-muted-foreground">
                        <span className="flex gap-0.5">
                          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
                          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500 [animation-delay:150ms]" />
                          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500 [animation-delay:300ms]" />
                        </span>
                        {t('console.streaming')}
                      </div>
                    )}
                  </div>
                )}
              </ScrollArea>
            </div>
          </TabsContent>

          <TabsContent value="context" className="mt-3 flex min-h-0 flex-1 flex-col">
            <ScrollArea className="h-full" viewportClassName="px-4 pb-3">
              {!hasContext ? (
                <EmptyState text={t('console.emptyContext')} />
              ) : (
                <div className="flex flex-col gap-3">
                  {contextEvent && (
                    <div>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">
                        {t('console.chars').replace('{count}', String(contextEvent.chars ?? 0))}
                      </div>
                      <pre className="whitespace-pre-wrap rounded-lg border border-border-2 bg-panel-2 p-2 font-mono text-[11px] text-muted-foreground">
                        {contextEvent.preview ?? ''}
                      </pre>
                    </div>
                  )}
                  {argsContext && (
                    <div>
                      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {t('console.contextArgs')}
                      </div>
                      <pre className="whitespace-pre-wrap rounded-lg border border-border-2 bg-panel-2 p-2 font-mono text-[11px] text-muted-foreground">
                        {argsContext}
                      </pre>
                    </div>
                  )}
                  {argsMessage && (
                    <div>
                      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {t('console.contextMessage')}
                      </div>
                      <pre className="whitespace-pre-wrap rounded-lg border border-border-2 bg-panel-2 p-2 font-mono text-[11px] text-muted-foreground">
                        {argsMessage}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </ScrollArea>
          </TabsContent>
        </Tabs>
      </div>
    </>
  )
}
