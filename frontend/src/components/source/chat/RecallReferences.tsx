'use client'

import { CornerUpRight, Highlighter } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { RecallRef } from '@/lib/types/api'
import { useTranslation } from '@/lib/hooks/use-translation'

/**
 * Recall breadcrumb pills for an AI chat message (study-memory Track C1).
 * Each pill points at a prior study trace — a past chat exchange or one of
 * the user's own highlights — related to this answer, WITHOUT restating its
 * content: the contract (`RecallRef`) deliberately carries no gist,
 * annotation note, or answer text, and this component renders only its
 * fields (spoiler guard, coordinator.md decision 5). There is no fetch here
 * — contrast `AnnotationReferences`' `AnnotationRefBody`, which fetches the
 * anchored block; the recall contract already carries everything shown.
 * Clicking is wired in Track C2 via the optional `onOpenRef` prop; v1 calls
 * it if present and is otherwise a no-op (no routing/store access here).
 * Renders nothing when `refs` is empty or absent.
 */
export function RecallReferences({
  refs,
  onOpenRef,
}: {
  refs: RecallRef[]
  onOpenRef?: (ref: RecallRef) => void
}) {
  const { t } = useTranslation()
  if (!refs.length) return null

  return (
    <div className="mt-1.5 w-full">
      <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-text-3">
        {t('chat.recallRelated')}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {refs.map((refItem, index) => {
          const isAnnotation = refItem.kind === 'annotation'
          const Icon = isAnnotation ? Highlighter : CornerUpRight
          const kindLabel = t(isAnnotation ? 'chat.recallKindAnnotation' : 'chat.recallKindExchange')
          const label = refItem.title?.trim() || kindLabel
          const key = refItem.annotation_id || refItem.session_id || `recall-${index}`

          return (
            <Popover key={key}>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  data-recall-kind={refItem.kind}
                  className="group/rref flex max-w-full items-center gap-1.5 rounded-full border border-border-2 bg-panel-2 py-1 pl-2 pr-2.5 text-left transition-colors hover:bg-accent-soft"
                >
                  <Icon className="h-3 w-3 flex-shrink-0 text-primary" aria-hidden="true" />
                  <span className="max-w-[180px] truncate text-[11px] font-medium text-foreground group-hover/rref:text-primary">
                    {label}
                  </span>
                  {refItem.page != null && (
                    <span className="flex-shrink-0 text-[10px] text-text-3">
                      {t('chat.recallRefPage').replace('{page}', String(refItem.page))}
                    </span>
                  )}
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-72 max-w-[calc(100vw-2rem)]" align="start">
                <div className="flex flex-col gap-1.5">
                  <p className="truncate text-[10.5px] font-medium uppercase tracking-[0.06em] text-text-3">
                    {kindLabel}
                  </p>
                  <p className="text-xs text-foreground whitespace-pre-wrap break-words">
                    {refItem.quote?.trim() || label}
                  </p>
                </div>
                {onOpenRef && (
                  <button
                    type="button"
                    onClick={() => onOpenRef(refItem)}
                    className="mt-2 flex items-center gap-1.5 text-[11px] font-medium text-primary hover:underline"
                  >
                    <CornerUpRight className="h-3 w-3" aria-hidden="true" />
                    {isAnnotation ? t('chat.recallJumpToHighlight') : t('chat.recallOpenSession')}
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
