'use client'

import { useRef, useState, type ReactNode } from 'react'
import { FileText, Lightbulb, StickyNote } from 'lucide-react'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/hooks/use-translation'
import { formatCompactNumber } from '@/lib/utils/format'
import type { BuildContextResponse } from '@/lib/types/api'

type ContextData = BuildContextResponse['context']
type ContextItem = Record<string, unknown>

// --- Safe field readers over the loosely-typed context payload -----------------
// The backend's /chat/context returns each source/note as Source.get_context()'s
// dict (see open_notebook/domain/notebook.py), so shapes vary by mode:
//   source insights → { id, title, insights }
//   source full     → { id, title, insights, abstract, outline } OR { ..., full_text }
//   note            → { id, title, content }

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function asArray(value: unknown): ContextItem[] {
  return Array.isArray(value) ? (value as ContextItem[]) : []
}

// Serialized size of an item, used as its relative weight when splitting the
// exact backend token total across rows (see estimateItemTokens).
function itemWeight(item: ContextItem): number {
  return JSON.stringify(item).length
}

// Distribute the backend's exact total token count across items in proportion to
// their serialized size. This keeps per-row figures consistent with the header
// total (they sum to it) instead of a standalone chars/4 guess that would visibly
// disagree with the real tokenizer for a single large source.
function estimateItemTokens(item: ContextItem, totalWeight: number, totalTokens: number): number {
  if (totalWeight <= 0) return 0
  return Math.round((itemWeight(item) / totalWeight) * totalTokens)
}

// Flatten Source.get_outline()'s nested tree into "Ch N: title (pp. X–Y)" lines,
// mirroring _format_outline_chapters() so the preview reads like the real prompt.
function flattenOutline(outline: ContextItem[], counter = { n: 0 }): string[] {
  const lines: string[] = []
  for (const node of outline) {
    counter.n += 1
    const title = asString(node.title) || 'Untitled'
    const start = node.page_start
    const end = node.page_end
    let pages = ''
    if (typeof start === 'number' && typeof end === 'number') pages = ` (pp. ${start}–${end})`
    else if (typeof start === 'number') pages = ` (p. ${start})`
    const summary = asString(node.summary)
    lines.push(`Ch ${counter.n}: ${title}${pages}${summary ? ` — ${summary}` : ''}`)
    lines.push(...flattenOutline(asArray(node.children), counter))
  }
  return lines
}

interface ContextPreviewPopoverProps {
  contextData: ContextData | null | undefined
  tokenCount: number
  charCount: number
  sourceCount: number
  notesCount: number
  children: ReactNode
}

/**
 * Hover-triggered, scrollable preview of exactly what's in the chat context
 * window. Wraps the dock's "N sources · M notes · k tokens" meter: hovering (or
 * focusing) the meter opens a card listing every source/note actually sent to the
 * model, with its contributed text and an approximate per-item token size. Built
 * on the controlled Popover (not a Tooltip) so the content is pointer-safe and
 * the body can be scrolled.
 */
export function ContextPreviewPopover({
  contextData,
  tokenCount,
  charCount,
  sourceCount,
  notesCount,
  children,
}: ContextPreviewPopoverProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const cancelClose = () => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }
  // Small grace delay so moving the pointer from the meter onto the card (across
  // the sideOffset gap) doesn't dismiss it.
  const scheduleClose = () => {
    cancelClose()
    closeTimer.current = setTimeout(() => setOpen(false), 140)
  }
  const openNow = () => {
    cancelClose()
    setOpen(true)
  }

  const sources = asArray(contextData?.sources)
  const notes = asArray(contextData?.notes)
  // Split the exact token total across all rows by relative size.
  const totalWeight =
    sources.reduce((sum, s) => sum + itemWeight(s), 0) +
    notes.reduce((sum, n) => sum + itemWeight(n), 0)
  // The context payload is built async (debounced) after selections change, so
  // it can briefly lag behind the meter. Distinguish "still building" (meter says
  // there's content but the payload hasn't landed) from a genuinely empty context.
  const building = !contextData && sourceCount + notesCount > 0
  const isEmpty = !building && sources.length === 0 && notes.length === 0

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          onMouseEnter={openNow}
          onMouseLeave={scheduleClose}
          onFocus={openNow}
          onBlur={scheduleClose}
          className="flex min-w-0 max-w-full cursor-default items-center rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          aria-label={t('chat.contextPreviewTitle')}
        >
          {children}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="end"
        sideOffset={8}
        onMouseEnter={openNow}
        onMouseLeave={scheduleClose}
        // Don't steal focus on a hover-open — keeps the composer caret in place.
        onOpenAutoFocus={(e) => e.preventDefault()}
        className="w-96 max-w-[calc(100vw-2rem)] p-0"
      >
        <div className="flex items-baseline justify-between gap-2 border-b px-3 py-2">
          <span className="text-xs font-medium">{t('chat.contextPreviewTitle')}</span>
          <span className="text-[11px] text-muted-foreground">
            {t('chat.contextPreviewTotal')
              .replace('{tokens}', formatCompactNumber(tokenCount))
              .replace('{chars}', formatCompactNumber(charCount))}
          </span>
        </div>

        {building ? (
          <p className="px-3 py-4 text-xs text-muted-foreground">
            {t('chat.contextPreviewBuilding')}
          </p>
        ) : isEmpty ? (
          <p className="px-3 py-4 text-xs text-muted-foreground">
            {t('chat.contextPreviewEmpty')}
          </p>
        ) : (
          <ScrollArea className="max-h-[50vh]">
            <div className="flex flex-col gap-3 px-3 py-3">
              {sources.length > 0 && (
                <section className="flex flex-col gap-2">
                  <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {t('chat.contextPreviewSources').replace('{count}', sources.length.toString())}
                  </h4>
                  {sources.map((item, i) => (
                    <SourceRow
                      key={asString(item.id) || `source-${i}`}
                      item={item}
                      tokens={estimateItemTokens(item, totalWeight, tokenCount)}
                      t={t}
                    />
                  ))}
                </section>
              )}
              {notes.length > 0 && (
                <section className="flex flex-col gap-2">
                  <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {t('chat.contextPreviewNotes').replace('{count}', notes.length.toString())}
                  </h4>
                  {notes.map((item, i) => (
                    <NoteRow
                      key={asString(item.id) || `note-${i}`}
                      item={item}
                      tokens={estimateItemTokens(item, totalWeight, tokenCount)}
                      t={t}
                    />
                  ))}
                </section>
              )}
              <p className="text-[10px] leading-snug text-muted-foreground/70">
                {t('chat.contextPreviewApproxNote')}
              </p>
            </div>
          </ScrollArea>
        )}
      </PopoverContent>
    </Popover>
  )
}

function ItemShell({
  icon,
  title,
  badge,
  tokens,
  children,
  t,
}: {
  icon: ReactNode
  title: string
  badge?: ReactNode
  tokens: number
  children?: ReactNode
  t: (key: string) => string
}) {
  return (
    <div className="rounded-md border bg-muted/30 px-2.5 py-2">
      <div className="flex items-center gap-1.5">
        {icon}
        <span className="min-w-0 flex-1 truncate text-xs font-medium">{title}</span>
        {badge}
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
          {t('chat.contextPreviewItemTokens').replace(
            '{tokens}',
            formatCompactNumber(tokens),
          )}
        </span>
      </div>
      {children}
    </div>
  )
}

function SourceRow({
  item,
  tokens,
  t,
}: {
  item: ContextItem
  tokens: number
  t: (key: string) => string
}) {
  const title = asString(item.title) || t('chat.contextPreviewUntitledSource')
  const abstract = asString(item.abstract)
  const outline = asArray(item.outline)
  const fullText = asString(item.full_text)
  const insights = asArray(item.insights)
  // Insights-only sources carry no long-form body; anything else is "full".
  const isFull = Boolean(abstract || outline.length > 0 || fullText)
  const chapters = flattenOutline(outline)

  return (
    <ItemShell
      t={t}
      tokens={tokens}
      title={title}
      icon={<FileText className="h-3.5 w-3.5 shrink-0 text-primary" />}
      badge={
        <Badge
          variant="outline"
          className="shrink-0 px-1.5 py-0 text-[10px] font-normal"
        >
          {isFull ? t('chat.contextPreviewModeFull') : t('chat.contextPreviewModeInsights')}
        </Badge>
      }
    >
      <div className="mt-1.5 flex flex-col gap-1.5">
        {abstract && (
          <p className="whitespace-pre-wrap break-words text-[11px] leading-snug text-muted-foreground">
            {abstract}
          </p>
        )}
        {chapters.length > 0 && (
          <ul className="flex flex-col gap-0.5">
            {chapters.map((line, i) => (
              <li
                key={i}
                className="break-words text-[11px] leading-snug text-muted-foreground"
              >
                {line}
              </li>
            ))}
          </ul>
        )}
        {fullText && (
          <p className="whitespace-pre-wrap break-words text-[11px] leading-snug text-muted-foreground">
            {fullText}
          </p>
        )}
        {insights.length > 0 && (
          <ul className="flex flex-col gap-0.5">
            {insights.map((insight, i) => {
              const content = asString(insight.content)
              if (!content) return null
              const type = asString(insight.insight_type) || t('chat.contextPreviewInsight')
              return (
                <li
                  key={i}
                  className="flex gap-1 break-words text-[11px] leading-snug text-muted-foreground"
                >
                  <Lightbulb className="mt-0.5 h-3 w-3 shrink-0 text-amber-600" />
                  <span>
                    <span className="font-medium text-foreground/80">{type}: </span>
                    {content}
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </ItemShell>
  )
}

function NoteRow({
  item,
  tokens,
  t,
}: {
  item: ContextItem
  tokens: number
  t: (key: string) => string
}) {
  const title = asString(item.title) || t('chat.contextPreviewUntitledNote')
  const content = asString(item.content)
  return (
    <ItemShell
      t={t}
      tokens={tokens}
      title={title}
      icon={<StickyNote className="h-3.5 w-3.5 shrink-0 text-primary" />}
    >
      {content && (
        <p className="mt-1.5 whitespace-pre-wrap break-words text-[11px] leading-snug text-muted-foreground">
          {content}
        </p>
      )}
    </ItemShell>
  )
}
