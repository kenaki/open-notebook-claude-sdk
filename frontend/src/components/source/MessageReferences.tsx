'use client'

import { FileText, StickyNote, Lightbulb, Sparkles } from 'lucide-react'
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
 * Numbered reference cards for an AI message's structured citations (Plan D /
 * Chunk 9). Each card shows the citation number, type icon, resolved title (or
 * the id as fallback) and a short snippet. Clicking opens the existing
 * source/note/insight modal via `onReferenceClick(type, bareId)` — kept wired so
 * Plan E can add the source-card flash without re-touching this component.
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
    <div className="w-full mt-1.5">
      <p className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-text-3 mb-1.5">
        {t('common.references')}
      </p>
      <div className="flex flex-col gap-1.5">
        {citations.map((citation) => {
          const Icon = TYPE_ICON[citation.type] ?? FileText
          return (
            <button
              key={`${citation.id}-${citation.number}`}
              type="button"
              data-citation-id={citation.id}
              data-citation-type={citation.type}
              onClick={() => onReferenceClick(citation.type, bareId(citation.id))}
              className="group flex items-start gap-2 text-left rounded-lg border border-border-2 bg-panel-2 hover:bg-accent-soft px-2.5 py-2 transition-colors"
            >
              <span className="flex-shrink-0 h-5 w-5 mt-0.5 rounded-full bg-accent-soft text-primary text-[11px] font-semibold flex items-center justify-center">
                {citation.number}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <Icon className="h-3 w-3 flex-shrink-0 text-text-3" aria-hidden="true" />
                  <span className="truncate text-xs font-medium text-foreground group-hover:text-primary">
                    {citation.title || citation.id}
                  </span>
                </span>
                {citation.snippet && (
                  <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground line-clamp-2">
                    {citation.snippet}
                  </span>
                )}
              </span>
            </button>
          )
        })}
      </div>
    </div>
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
