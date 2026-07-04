'use client'

import { useMemo, useState } from 'react'
import { SlidersHorizontal, ListChecks, FileText, StickyNote } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ContextToggle } from '@/components/common/ContextToggle'
import {
  applyBulkSourceContext,
  applyBulkNoteContext,
  type SourceBulkAction,
  type NoteContextDefault,
} from '@/lib/utils/source-context'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { ContextMode, ContextSelections } from '@/lib/types/notebook-context'
import type { SourceListResponse, NoteResponse } from '@/lib/types/api'

interface SideChatContextPopoverProps {
  sources: SourceListResponse[]
  notes: NoteResponse[]
  // The notebook's global drawer selection — the read-only baseline shown (and
  // sent) while this chat inherits (`contextConfig == null`), and the seed used
  // when the user makes this chat's first explicit override.
  notebookDefault: ContextSelections
  // This session's own selection; `null`/`undefined` means "inherit
  // `notebookDefault`" (chat-foundation ctx-1/ctx-2).
  contextConfig: ContextSelections | null | undefined
  onChange: (next: ContextSelections) => void
  onReset: () => void
}

/**
 * Per-side-chat Context editor (chat-foundation F5). Lets a popped side chat opt
 * sources/notes in or out of ITS OWN context window, independent of the
 * notebook's global drawer selection — F2 already wires the read/send side (a
 * session with an explicit `context_config` sends that instead of the global
 * selection). Reuses `ContextToggle` + the bulk-context helpers verbatim; no new
 * toggle logic, no `insightsSnapshot` helper (quote-only default per ctx-3).
 */
export function SideChatContextPopover({
  sources,
  notes,
  notebookDefault,
  contextConfig,
  onChange,
  onReset,
}: SideChatContextPopoverProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const inheriting = contextConfig == null
  // What's actually in effect right now, whichever side it comes from.
  const effective = contextConfig ?? notebookDefault

  const includedCount = useMemo(() => {
    let count = 0
    sources.forEach((source) => {
      if ((effective.sources[source.id] ?? 'off') !== 'off') count++
    })
    notes.forEach((note) => {
      if ((effective.notes[note.id] ?? 'off') !== 'off') count++
    })
    return count
  }, [sources, notes, effective])

  // Any per-item edit promotes this chat to an explicit selection, seeded from
  // whatever was in effect a moment ago (inherited or not) — so flipping one
  // toggle doesn't silently drop the rest of the notebook default.
  const updateItem = (itemId: string, mode: ContextMode, type: 'source' | 'note') => {
    const next: ContextSelections = {
      sources: { ...effective.sources },
      notes: { ...effective.notes },
    }
    if (type === 'source') next.sources[itemId] = mode
    else next.notes[itemId] = mode
    onChange(next)
  }

  const bulkSources = (action: SourceBulkAction) => {
    onChange({
      sources: applyBulkSourceContext(effective.sources, sources, action),
      notes: { ...effective.notes },
    })
  }

  const bulkNotes = (action: NoteContextDefault) => {
    onChange({
      sources: { ...effective.sources },
      notes: applyBulkNoteContext(effective.notes, notes, action),
    })
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          title={t('chat.contextForThisChat')}
          aria-label={
            includedCount > 0
              ? t('chat.contextIncludedCount').replace('{count}', includedCount.toString())
              : t('chat.contextForThisChat')
          }
          className="relative h-7 w-7 p-0 text-muted-foreground hover:bg-accent"
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          {includedCount > 0 && (
            <span className="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[9px] font-semibold leading-none text-primary-foreground">
              {includedCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={6}
        className="flex w-80 max-w-[calc(100vw-2rem)] flex-col overflow-hidden p-0"
      >
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-2">
          <span className="text-xs font-semibold text-foreground">{t('chat.contextForThisChat')}</span>
          {(sources.length > 0 || notes.length > 0) && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0" title={t('sources.bulkContext')}>
                  <ListChecks className="h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                {sources.length > 0 && (
                  <>
                    <DropdownMenuLabel className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      <FileText className="h-3 w-3" />
                      {t('navigation.sources')}
                    </DropdownMenuLabel>
                    <DropdownMenuItem onClick={() => bulkSources('insights')}>
                      {t('sources.includeAllInsights')}
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => bulkSources('full')}>
                      {t('sources.includeAllFull')}
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => bulkSources('exclude')}>
                      {t('sources.excludeAllFromContext')}
                    </DropdownMenuItem>
                  </>
                )}
                {sources.length > 0 && notes.length > 0 && <DropdownMenuSeparator />}
                {notes.length > 0 && (
                  <>
                    <DropdownMenuLabel className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      <StickyNote className="h-3 w-3" />
                      {t('common.notes')}
                    </DropdownMenuLabel>
                    <DropdownMenuItem onClick={() => bulkNotes('include')}>
                      {t('sources.includeAllInContext')}
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => bulkNotes('exclude')}>
                      {t('sources.excludeAllFromContext')}
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        {inheriting && (
          <p className="shrink-0 border-b border-border bg-muted/40 px-3 py-1.5 text-[11px] text-muted-foreground">
            {t('chat.inheritingNotebookDefault')}
          </p>
        )}

        <ScrollArea className="min-h-0 max-h-80 flex-1" viewportClassName="overscroll-contain">
          <div className="flex flex-col gap-0.5 px-1.5 py-1.5">
            {sources.map((source) => (
              <div
                key={source.id}
                className="flex items-center justify-between gap-2 rounded px-1.5 py-1 hover:bg-accent-soft"
              >
                <span
                  className="min-w-0 flex-1 truncate text-xs text-foreground"
                  title={source.title ?? undefined}
                >
                  {source.title || t('chat.contextPreviewUntitledSource')}
                </span>
                <ContextToggle
                  mode={effective.sources[source.id] ?? 'off'}
                  hasInsights={source.insights_count > 0}
                  onChange={(mode) => updateItem(source.id, mode, 'source')}
                />
              </div>
            ))}
            {notes.map((note) => (
              <div
                key={note.id}
                className="flex items-center justify-between gap-2 rounded px-1.5 py-1 hover:bg-accent-soft"
              >
                <span
                  className="min-w-0 flex-1 truncate text-xs text-foreground"
                  title={note.title ?? undefined}
                >
                  {note.title || t('chat.contextPreviewUntitledNote')}
                </span>
                <ContextToggle
                  mode={effective.notes[note.id] ?? 'off'}
                  hasInsights={false}
                  onChange={(mode) => updateItem(note.id, mode, 'note')}
                />
              </div>
            ))}
          </div>
        </ScrollArea>

        <div className="shrink-0 border-t border-border px-3 py-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="w-full justify-center text-xs"
            disabled={inheriting}
            onClick={onReset}
          >
            {t('chat.resetToNotebookDefault')}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
