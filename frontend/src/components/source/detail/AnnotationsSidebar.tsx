'use client'

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Layers, MessageSquare, PanelRightClose, PanelRightOpen, Sparkles } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { cn } from '@/lib/utils'
import { resolveTagColorKey, tagColorStyle } from '@/lib/utils/tag-colors'
import { sourcesApi } from '@/lib/api/sources'
import { useAnnotationCitingCounts } from '@/lib/hooks/use-annotation-citations'
import {
  GLOBAL_SIDEBAR_KEY,
  useAnnotationsSidebarStore,
} from '@/lib/stores/annotations-sidebar-store'
import { HIGHLIGHT_PALETTE } from './AnnotationHighlightPopover'
import type { Annotation, SourceSectionNode } from '@/lib/types/api'

interface AnnotationsSidebarProps {
  annotations: Annotation[]
  onJumpTo: (annotation: Annotation) => void
  /**
   * Source id — enables the optional group-by-section view (fetches the
   * chapter tree lazily, only while grouping is on). Omitted → no grouping.
   */
  sourceId?: string
  /**
   * "Ask AI about <tag>": called with the active tag. The caller gathers the
   * quotes and sends them to the chat. Omitted where no chat is wired — the
   * button hides.
   */
  onAskAiAboutTag?: (tag: string) => void
}

/** Top-level chapter (≈ section_path[0]) whose page range contains `page`.
 *  Null when no top-level section matches → grouped under "Unsectioned". */
function chapterTitleForPage(topLevel: SourceSectionNode[], page: number): string | null {
  for (const node of topLevel) {
    const start = node.page_start
    const end = node.page_end
    if (start != null && page >= start && (end == null || page <= end)) {
      return node.title?.trim() || null
    }
  }
  return null
}

/**
 * Document Foundation Phase4: compact list of a source's saved highlights,
 * sitting beside the PDFViewer and the ReaderView. Purely presentational —
 * jumping is delegated to the caller (which knows how to reach a highlight in
 * its own view). Header offers a per-color filter and a per-tag filter;
 * colors/tags with no highlights are hidden or dimmed.
 *
 * Collapses to a narrow rail, giving the reader back its line width. The state
 * lives in a per-source store, not local state, because both tabs mount their
 * own instance and stay mounted — see `annotations-sidebar-store`.
 */
/** One highlight row — shared by the flat list and the grouped view. */
function AnnotationRow({
  annotation,
  onJumpTo,
  citingCount = 0,
}: {
  annotation: Annotation
  onJumpTo: (annotation: Annotation) => void
  /** Number of chat sessions citing this highlight (Track B4) — badge only. */
  citingCount?: number
}) {
  const { t } = useTranslation()
  return (
    <button
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
      {citingCount > 0 && (
        <span
          title={t('sources.annotations.linkedChats')}
          className="mt-0.5 flex shrink-0 items-center gap-0.5 text-[10px] text-muted-foreground"
        >
          <MessageSquare className="h-3 w-3" aria-hidden="true" />
          {citingCount}
        </span>
      )}
    </button>
  )
}

export function AnnotationsSidebar({
  annotations,
  onJumpTo,
  sourceId,
  onAskAiAboutTag,
}: AnnotationsSidebarProps) {
  const { t } = useTranslation()
  const [colorFilter, setColorFilter] = useState<string | null>(null)
  const [tagFilter, setTagFilter] = useState<string | null>(null)
  const [groupBySection, setGroupBySection] = useState(false)

  const storeKey = sourceId ?? GLOBAL_SIDEBAR_KEY
  const collapsed = useAnnotationsSidebarStore((s) => s.collapsedBySource[storeKey] ?? false)
  const toggleCollapsed = useAnnotationsSidebarStore((s) => s.toggle)

  // All tags currently in use, in first-seen order.
  const allTags = useMemo(
    () => [...new Set(annotations.flatMap((a) => a.tags ?? []))],
    [annotations]
  )

  // Bulk citing counts for this source (Track B4) → per-row "linked chats"
  // badge. One request per source; badge is display-only. Absent → no badge.
  const { data: citingCountsData } = useAnnotationCitingCounts(sourceId)
  const citingCounts = citingCountsData?.counts

  // Chapter tree — fetched lazily, only while group-by-section is on. Under the
  // ['sources', id, …] tree so a broad source invalidation refreshes it.
  const { data: sectionData } = useQuery({
    queryKey: ['sources', sourceId ?? '', 'sections', 'annotations-group'],
    queryFn: () => sourcesApi.getSections(sourceId as string),
    enabled: !!sourceId && groupBySection,
    staleTime: 5 * 60 * 1000,
    meta: { silent: true },
  })

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

  // Group the visible highlights by top-level chapter (section_path[0]),
  // preserving first-seen order; unmatched pages fall under "Unsectioned".
  const grouped = useMemo(() => {
    if (!groupBySection) return null
    const topLevel = sectionData?.sections ?? []
    const unsectioned = t('sources.annotations.unsectioned')
    const map = new Map<string, Annotation[]>()
    for (const a of visible) {
      const title = chapterTitleForPage(topLevel, a.page) || unsectioned
      const bucket = map.get(title)
      if (bucket) bucket.push(a)
      else map.set(title, [a])
    }
    return [...map.entries()]
  }, [groupBySection, visible, sectionData, t])

  if (collapsed) {
    return (
      <div className="flex w-8 shrink-0 flex-col items-center gap-2 rounded-md border border-border py-2">
        <button
          type="button"
          aria-expanded={false}
          title={t('sources.annotations.expandSidebar')}
          aria-label={t('sources.annotations.expandSidebar')}
          onClick={() => toggleCollapsed(storeKey)}
          className="rounded-sm p-0.5 text-muted-foreground transition-colors hover:text-foreground"
        >
          <PanelRightOpen className="h-4 w-4" aria-hidden="true" />
        </button>
        <span
          aria-hidden="true"
          className="[writing-mode:vertical-rl] select-none text-xs font-semibold text-muted-foreground"
        >
          {t('sources.annotations.title')}
          {annotations.length > 0 && ` (${annotations.length})`}
        </span>
      </div>
    )
  }

  return (
    <div className="flex w-56 shrink-0 flex-col overflow-hidden rounded-md border border-border">
      <div className="border-b border-border px-2 py-1.5">
        <div className="flex items-center justify-between gap-1">
          <div className="text-xs font-semibold text-muted-foreground">
            {t('sources.annotations.title')}
            {annotations.length > 0 && ` (${annotations.length})`}
          </div>
          <div className="flex items-center gap-0.5">
            {sourceId && annotations.length > 0 && (
              <button
                type="button"
                aria-pressed={groupBySection}
                title={t('sources.annotations.groupBySection')}
                aria-label={t('sources.annotations.groupBySection')}
                onClick={() => setGroupBySection((prev) => !prev)}
                className={cn(
                  'rounded-sm p-0.5 transition-colors',
                  groupBySection
                    ? 'text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <Layers className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            )}
            <button
              type="button"
              aria-expanded
              title={t('sources.annotations.collapseSidebar')}
              aria-label={t('sources.annotations.collapseSidebar')}
              onClick={() => toggleCollapsed(storeKey)}
              className="rounded-sm p-0.5 text-muted-foreground transition-colors hover:text-foreground"
            >
              <PanelRightClose className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
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
        ) : grouped ? (
          grouped.map(([title, group]) => (
            <div key={title} className="mb-1">
              <div className="sticky top-0 truncate bg-background/95 px-1.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {title}
              </div>
              {group.map((annotation) => (
                <AnnotationRow
                  key={annotation.id}
                  annotation={annotation}
                  onJumpTo={onJumpTo}
                  citingCount={citingCounts?.[annotation.id] ?? 0}
                />
              ))}
            </div>
          ))
        ) : (
          visible.map((annotation) => (
            <AnnotationRow
              key={annotation.id}
              annotation={annotation}
              onJumpTo={onJumpTo}
              citingCount={citingCounts?.[annotation.id] ?? 0}
            />
          ))
        )}
      </div>
    </div>
  )
}
