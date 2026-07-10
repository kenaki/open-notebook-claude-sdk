'use client'

import { useEffect, useState } from 'react'
import { BookMarked, ChevronRight, FileText, StickyNote, Lightbulb, Sparkles, Highlighter, CornerUpRight } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useBlock } from '@/lib/hooks/use-source-blocks'
import { getApiUrl } from '@/lib/config'
import { AnnotationRef, Citation } from '@/lib/types/api'
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

// Resolve a fetchable src for a backend block-crop url ("/api/sources/.../image"),
// mirroring MessageMedia: prefix the resolved API base (cached after first call).
function useApiBase(): string {
  const [base, setBase] = useState('')
  useEffect(() => {
    let active = true
    getApiUrl()
      .then((u) => active && setBase(u))
      .catch(() => {})
    return () => {
      active = false
    }
  }, [])
  return base
}

// Popover body for one annotation pill: the anchored block's content. Equation →
// KaTeX (error-fallback to raw latex via rehype-katex, Decision #7); figure/table
// → the crop image; otherwise a text excerpt + section breadcrumb. Falls back to
// the stored quote for a legacy (un-anchored) highlight or while the block loads.
function AnnotationRefBody({
  sourceId,
  refItem,
}: {
  // Fallback when the ref itself carries no source_id (source chat's surface
  // always has one). cross-interface-study Track B3: a notebook-chat ref
  // prefers its own `refItem.source_id` since it can point at a different
  // source than any single surface-level id.
  sourceId?: string
  refItem: AnnotationRef
}) {
  const { t } = useTranslation()
  const base = useApiBase()
  const effectiveSourceId = refItem.source_id ?? sourceId
  const hasAnchor = refItem.block_seq != null
  const block = useBlock(effectiveSourceId, hasAnchor ? refItem.block_seq : null, {
    enabled: hasAnchor,
  })

  const breadcrumb = (block.data?.section_path ?? []).filter(Boolean).join(' › ')

  let content: React.ReactNode
  if (!hasAnchor) {
    // Legacy highlight — no block anchor, show the raw quote.
    content = (
      <p className="text-xs text-foreground whitespace-pre-wrap break-words">
        {refItem.quote || t('chat.annotationRefEmpty')}
      </p>
    )
  } else if (block.isLoading) {
    content = (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <LoadingSpinner size="sm" />
        {t('common.loading')}
      </div>
    )
  } else if (block.isError || !block.data) {
    content = (
      <p className="text-xs text-foreground whitespace-pre-wrap break-words">
        {refItem.quote || t('chat.annotationRefEmpty')}
      </p>
    )
  } else if (block.data.type === 'equation' && block.data.latex) {
    content = (
      <div className="chat-markdown prose prose-sm prose-neutral dark:prose-invert max-w-none overflow-x-auto">
        <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
          {`$$\n${block.data.latex}\n$$`}
        </ReactMarkdown>
      </div>
    )
  } else if (
    (block.data.type === 'figure' || block.data.type === 'table') &&
    block.data.image_url
  ) {
    content = (
      /* eslint-disable-next-line @next/next/no-img-element */
      <img
        src={`${base}${block.data.image_url}`}
        alt={block.data.text || t('chat.annotationRefFigure')}
        className="max-h-64 w-auto max-w-full rounded border border-border"
      />
    )
  } else {
    content = (
      <p className="text-xs text-foreground whitespace-pre-wrap break-words line-clamp-6">
        {block.data.text || refItem.quote || t('chat.annotationRefEmpty')}
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      {breadcrumb && (
        <p className="truncate text-[10.5px] font-medium uppercase tracking-[0.06em] text-text-3">
          {breadcrumb}
        </p>
      )}
      {content}
    </div>
  )
}

/**
 * Annotation reference pills for a chat message (pdf-block-ingestion Track D4).
 * Each pill shows the highlighted quote snippet + page; clicking opens a popover
 * with the anchored block's rendered content (KaTeX equation / figure crop / text
 * excerpt) and a "jump to highlight" action wired by the caller (`onJumpTo`,
 * routed per active tab in D8). Renders nothing when a message carries no refs.
 */
export function AnnotationReferences({
  refs,
  sourceId,
  onJumpTo,
}: {
  refs: AnnotationRef[]
  // cross-interface-study Track B3: optional — notebook chat has no single
  // surface-level source; each ref falls back to its own `source_id` instead
  // (passed straight through to AnnotationRefBody for block hydration).
  sourceId?: string
  onJumpTo?: (ref: AnnotationRef) => void
}) {
  const { t } = useTranslation()
  if (!refs.length) return null

  return (
    <div className="mt-1.5 w-full">
      <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-text-3">
        {t('chat.referencedHighlights')}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {refs.map((refItem) => {
          const snippet = refItem.quote?.trim() || t('chat.annotationRefEmpty')
          return (
            <Popover key={refItem.id}>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  data-annotation-id={refItem.id}
                  className="group/aref flex max-w-full items-center gap-1.5 rounded-full border border-border-2 bg-panel-2 py-1 pl-2 pr-2.5 text-left transition-colors hover:bg-accent-soft"
                >
                  <Highlighter className="h-3 w-3 flex-shrink-0 text-primary" aria-hidden="true" />
                  <span className="max-w-[180px] truncate text-[11px] font-medium text-foreground group-hover/aref:text-primary">
                    {snippet}
                  </span>
                  {refItem.page != null && (
                    <span className="flex-shrink-0 text-[10px] text-text-3">
                      {t('chat.annotationRefPage').replace('{page}', String(refItem.page))}
                    </span>
                  )}
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-72 max-w-[calc(100vw-2rem)]" align="start">
                <AnnotationRefBody sourceId={sourceId} refItem={refItem} />
                {onJumpTo && (
                  <button
                    type="button"
                    onClick={() => onJumpTo(refItem)}
                    className="mt-2 flex items-center gap-1.5 text-[11px] font-medium text-primary hover:underline"
                  >
                    <CornerUpRight className="h-3 w-3" aria-hidden="true" />
                    {t('chat.jumpToHighlight')}
                  </button>
                )}
              </PopoverContent>
            </Popover>
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
