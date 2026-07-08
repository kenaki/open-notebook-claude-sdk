'use client'

import { BookMarked, ChevronRight, FileText, StickyNote, Lightbulb, Sparkles } from 'lucide-react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Citation } from '@/lib/types/api'
import { useTranslation } from '@/lib/hooks/use-translation'

// The backend Citation.id carries its type prefix (e.g. "source:abc123"); the
// modal/openModal path expects the bare id. Strip the leading "<type>:".
function bareId(id: string): string {
  return id.replace(/^[^:]+:/, '')
}

const TYPE_ICON = {
  source: FileText,
  note: StickyNote,
  source_insight: Lightbulb,
} as const

/**
 * Collapsible reference list for an AI message's structured citations (Plan D /
 * Chunk 9). Collapsed by default to a single summary row ("References · N",
 * same visual language as ToolUseDisclosure); expanding reveals compact pill
 * chips — citation number, type icon, truncated title (id as fallback) — that
 * wrap instead of stacking full-width. The snippet moves to the chip's hover
 * tooltip. Clicking a chip opens the existing source/note/insight modal via
 * `onReferenceClick(type, bareId)` — kept wired so Plan E can add the
 * source-card flash without re-touching this component.
 */
export function MessageReferences({
  citations,
  onReferenceClick,
}: {
  citations: Citation[]
  onReferenceClick: (type: string, id: string) => void
}) {
  const { t } = useTranslation()
  if (!citations.length) return null

  return (
    <Collapsible className="w-full mt-1.5">
      <CollapsibleTrigger className="group flex w-full items-center gap-1.5 rounded-lg border border-border-2 bg-panel-2 px-2.5 py-1.5 text-left text-xs text-muted-foreground transition-colors hover:bg-accent-soft">
        <BookMarked className="h-3.5 w-3.5 flex-shrink-0 text-text-3" aria-hidden="true" />
        <span className="font-medium text-foreground">{t('common.references')}</span>
        <span className="text-text-3">· {citations.length}</span>
        <ChevronRight
          className="ml-auto h-3.5 w-3.5 flex-shrink-0 text-text-3 transition-transform duration-[0.18s] group-data-[state=open]:rotate-90"
          aria-hidden="true"
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-1.5 flex flex-wrap gap-1.5 pl-1">
          {citations.map((citation) => {
            const Icon = TYPE_ICON[citation.type] ?? FileText
            return (
              <button
                key={`${citation.id}-${citation.number}`}
                type="button"
                data-citation-id={citation.id}
                data-citation-type={citation.type}
                title={citation.snippet || undefined}
                onClick={() => onReferenceClick(citation.type, bareId(citation.id))}
                className="group/ref flex max-w-full items-center gap-1.5 rounded-full border border-border-2 bg-panel-2 py-1 pl-1 pr-2.5 text-left transition-colors hover:bg-accent-soft"
              >
                <span className="flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full bg-accent-soft text-[10px] font-semibold text-primary">
                  {citation.number}
                </span>
                <Icon className="h-3 w-3 flex-shrink-0 text-text-3" aria-hidden="true" />
                <span className="max-w-[180px] truncate text-[11px] font-medium text-foreground group-hover/ref:text-primary">
                  {citation.title || bareId(citation.id)}
                </span>
              </button>
            )
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/**
 * Suggested follow-up question chips (Plan D / Chunk 9). Clicking a chip sends
 * that question as the next message.
 */
export function FollowupChips({
  followups,
  onSelect,
  disabled = false,
}: {
  followups: string[]
  onSelect: (question: string) => void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  if (!followups.length) return null

  return (
    <div className="w-full mt-1.5">
      <p className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-text-3 mb-1.5">
        {t('chat.suggestedFollowups')}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {followups.map((question) => (
          <button
            key={question}
            type="button"
            onClick={() => onSelect(question)}
            disabled={disabled}
            className="flex items-center gap-1.5 rounded-full border border-border bg-card hover:bg-accent px-3 py-1.5 text-xs text-foreground transition-colors disabled:opacity-50"
          >
            <Sparkles className="h-3 w-3 flex-shrink-0 text-primary" aria-hidden="true" />
            <span className="text-left">{question}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
