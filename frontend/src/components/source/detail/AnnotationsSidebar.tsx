'use client'

import { useEffect, useMemo, useState } from 'react'
import { Sparkles } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { cn } from '@/lib/utils'
import { resolveTagColorKey, tagColorStyle } from '@/lib/utils/tag-colors'
import { HIGHLIGHT_PALETTE } from './AnnotationHighlightPopover'
import type { Annotation } from '@/lib/types/api'

interface AnnotationsSidebarProps {
  annotations: Annotation[]
  onJumpTo: (annotation: Annotation) => void
  /**
   * "Ask AI about <tag>": called with the active tag. The caller gathers the
   * quotes and sends them to the chat. Omitted where no chat is wired — the
   * button hides.
   */
  onAskAiAboutTag?: (tag: string) => void
}

/**
 * Document Foundation Phase4: compact list of a PDF source's saved
 * highlights, sitting beside the PDFViewer. Purely presentational — jumping
 * is delegated to the caller (which owns the highlight plugin instance).
 * Header offers a per-color filter and a per-tag filter; colors/tags with no
 * highlights are hidden or dimmed.
 */
export function AnnotationsSidebar({
  annotations,
  onJumpTo,
  onAskAiAboutTag,
}: AnnotationsSidebarProps) {
  const { t } = useTranslation()
  const [colorFilter, setColorFilter] = useState<string | null>(null)
  const [tagFilter, setTagFilter] = useState<string | null>(null)

  // All tags currently in use, in first-seen order.
  const allTags = useMemo(
    () => [...new Set(annotations.flatMap((a) => a.tags ?? []))],
    [annotations]
  )

  // If the last highlight of the filtered color is deleted, fall back to All.
  useEffect(() => {
    if (colorFilter && !annotations.some((a) => a.color === colorFilter)) {
      setColorFilter(null)
    }
  }, [annotations, colorFilter])

  // Same for the tag filter when its last highlight loses the tag / is deleted.
  useEffect(() => {
    if (tagFilter && !allTags.includes(tagFilter)) {
      setTagFilter(null)
    }
  }, [allTags, tagFilter])

  const visible = annotations.filter(
    (a) =>
      (!colorFilter || a.color === colorFilter) &&
      (!tagFilter || (a.tags ?? []).includes(tagFilter))
  )

  return (
    <div className="flex w-56 shrink-0 flex-col overflow-hidden rounded-md border border-border">
      <div className="border-b border-border px-2 py-1.5">
        <div className="text-xs font-semibold text-muted-foreground">
          {t('sources.annotations.title')}
          {annotations.length > 0 && ` (${annotations.length})`}
        </div>
        {annotations.length > 0 && (
          <div className="mt-1.5 flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setColorFilter(null)}
              className={`rounded-sm px-1 text-[11px] transition-colors ${
                colorFilter === null
                  ? 'font-medium text-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {t('sources.annotations.filterAll')}
            </button>
            {HIGHLIGHT_PALETTE.map(({ value, nameKey }) => {
              const count = annotations.filter((a) => a.color === value).length
              return (
                <button
                  key={value}
                  type="button"
                  disabled={count === 0}
                  title={`${t(nameKey)}${count ? ` (${count})` : ''}`}
                  aria-label={t(nameKey)}
                  aria-pressed={colorFilter === value}
                  onClick={() =>
                    setColorFilter((prev) => (prev === value ? null : value))
                  }
                  className={`h-3.5 w-3.5 rounded-full transition-transform ${
                    colorFilter === value
                      ? 'ring-2 ring-foreground ring-offset-1 ring-offset-background'
                      : ''
                  } ${count === 0 ? 'cursor-default opacity-25' : 'hover:scale-110'}`}
                  style={{ backgroundColor: value }}
                />
              )
            })}
          </div>
        )}
        {allTags.length > 0 && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1">
            {allTags.map((tag) => {
              const style = tagColorStyle(resolveTagColorKey(tag, {}))
              const count = annotations.filter((a) => (a.tags ?? []).includes(tag)).length
              const active = tagFilter === tag
              return (
                <button
                  key={tag}
                  type="button"
                  aria-pressed={active}
                  title={`${tag} (${count})`}
                  onClick={() => setTagFilter((prev) => (prev === tag ? null : tag))}
                  className={cn(
                    'inline-flex max-w-full items-center gap-1 truncate rounded-full px-1.5 py-0.5 text-[10px] transition-shadow',
                    style.chip,
                    active ? 'ring-2 ring-current/50' : 'opacity-80 hover:opacity-100'
                  )}
                >
                  <span className="truncate">{tag}</span>
                  <span className="opacity-70">{count}</span>
                </button>
              )
            })}
          </div>
        )}
        {tagFilter && onAskAiAboutTag && (
          <button
            type="button"
            onClick={() => onAskAiAboutTag(tagFilter)}
            className="mt-1.5 flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-accent-soft"
          >
            <Sparkles className="h-3 w-3" aria-hidden="true" />
            {t('sources.annotations.askAiAboutTag').replace('{tag}', tagFilter)}
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {annotations.length === 0 ? (
          <p className="p-2 text-xs text-muted-foreground">{t('sources.annotations.emptyState')}</p>
        ) : (
          visible.map((annotation) => (
            <button
              key={annotation.id}
              type="button"
              onClick={() => onJumpTo(annotation)}
              className="flex w-full items-start gap-1.5 rounded-sm p-1.5 text-left text-xs hover:bg-muted"
            >
              <span
                className="mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: annotation.color }}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-muted-foreground">
                  {t('sources.annotations.pageLabel').replace('{page}', String(annotation.page))}
                </span>
                <span className="line-clamp-2 block">{annotation.note || annotation.quote || ''}</span>
                {annotation.tags?.length > 0 && (
                  <span className="mt-1 flex flex-wrap gap-1">
                    {annotation.tags.map((tag) => {
                      const style = tagColorStyle(resolveTagColorKey(tag, {}))
                      return (
                        <span
                          key={tag}
                          className={cn(
                            'inline-block max-w-full truncate rounded-full px-1.5 py-0 text-[10px]',
                            style.chip
                          )}
                        >
                          {tag}
                        </span>
                      )
                    })}
                  </span>
                )}
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
