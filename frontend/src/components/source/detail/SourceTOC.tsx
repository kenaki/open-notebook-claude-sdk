'use client'

import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, MoreVertical } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { SourceSectionNode } from '@/lib/types/api'

/** Per-chapter AI action fired from a section row's ⋮ menu (C4). */
export type SectionActionKind = 'summarize' | 'quiz'

interface SourceTOCProps {
  sections: SourceSectionNode[]
  activeSectionId: string | null
  onSectionClick: (id: string) => void
  // C4: per-chapter AI actions (Summarize / Quiz me) dispatched to the source
  // chat. When omitted, the ⋮ menu is hidden (surfaces with no chat to send to).
  onSectionAction?: (kind: SectionActionKind, section: SourceSectionNode) => void
}

/**
 * Returns the ancestor-id chain (root → parent) leading to `targetId`, or null
 * if `targetId` isn't in the tree. Used to auto-expand collapsed branches when
 * the active section changes (e.g. via citation-jump in C4).
 */
function collectAncestorIds(
  nodes: SourceSectionNode[],
  targetId: string,
  ancestors: string[] = []
): string[] | null {
  for (const node of nodes) {
    if (node.id === targetId) return ancestors
    if (node.children?.length) {
      const found = collectAncestorIds(node.children, targetId, [...ancestors, node.id])
      if (found) return found
    }
  }
  return null
}

/** "pp. 12–18" / "p. 12" — null when the section carries no page info. */
export function getSectionPageRangeLabel(section: SourceSectionNode): string | null {
  const { page_start: start, page_end: end } = section
  if (start == null && end == null) return null
  if (start != null && end != null && start !== end) return `pp. ${start}–${end}`
  return `p. ${start ?? end}`
}

function SectionRow({
  section,
  depth,
  activeSectionId,
  onSectionClick,
  expandedIds,
  onToggle,
  untitledLabel,
  onSectionAction,
  labels,
}: {
  section: SourceSectionNode
  depth: number
  activeSectionId: string | null
  onSectionClick: (id: string) => void
  expandedIds: Set<string>
  onToggle: (id: string) => void
  untitledLabel: string
  onSectionAction?: (kind: SectionActionKind, section: SourceSectionNode) => void
  labels: { actions: string; summarize: string; quiz: string }
}) {
  const hasChildren = section.children.length > 0
  const isExpanded = expandedIds.has(section.id)
  const isActive = section.id === activeSectionId
  const title = section.title?.trim() || untitledLabel
  const range = getSectionPageRangeLabel(section)

  return (
    <div>
      <div
        data-section-id={section.id}
        role="button"
        tabIndex={0}
        onClick={() => onSectionClick(section.id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onSectionClick(section.id)
          }
        }}
        className={cn(
          'group flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm cursor-pointer hover:bg-muted transition-colors',
          isActive ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground'
        )}
        style={{ paddingLeft: `${8 + depth * 14}px` }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onToggle(section.id)
            }}
            className="shrink-0 -ml-1 rounded p-0.5 hover:bg-accent"
          >
            {isExpanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
          </button>
        ) : (
          <span className="w-4 shrink-0" aria-hidden="true" />
        )}
        <span className="flex-1 truncate">{title}</span>
        {range && <span className="shrink-0 text-xs text-muted-foreground">{range}</span>}
        {onSectionAction && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={labels.actions}
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
                className="shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:bg-accent focus:opacity-100 focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100"
              >
                <MoreVertical className="h-3.5 w-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
              <DropdownMenuItem onSelect={() => onSectionAction('summarize', section)}>
                {labels.summarize}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onSectionAction('quiz', section)}>
                {labels.quiz}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      {hasChildren && isExpanded && (
        <div>
          {section.children.map((child) => (
            <SectionRow
              key={child.id}
              section={child}
              depth={depth + 1}
              activeSectionId={activeSectionId}
              onSectionClick={onSectionClick}
              expandedIds={expandedIds}
              onToggle={onToggle}
              untitledLabel={untitledLabel}
              onSectionAction={onSectionAction}
              labels={labels}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * Sticky, collapsible chapter tree for a chaptered source (Document Foundation
 * Track C, Chunk C3). Top-level (level 1) rows are always visible; deeper rows
 * (level 2+) collapse under their parent until expanded — auto-expanding along
 * the path to whichever section is active.
 */
export function SourceTOC({ sections, activeSectionId, onSectionClick, onSectionAction }: SourceTOCProps) {
  const { t } = useTranslation()
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set())
  const actionLabels = {
    actions: t('sources.sectionActions'),
    summarize: t('sources.summarize'),
    quiz: t('sources.quizMe'),
  }

  useEffect(() => {
    if (!activeSectionId) return
    const ancestors = collectAncestorIds(sections, activeSectionId)
    if (ancestors && ancestors.length > 0) {
      setExpandedIds((prev) => {
        const next = new Set(prev)
        ancestors.forEach((id) => next.add(id))
        return next
      })
    }
  }, [activeSectionId, sections])

  const handleToggle = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  if (sections.length === 0) return null

  return (
    <nav
      aria-label={t('sources.tableOfContents')}
      className="w-full shrink-0 lg:sticky lg:top-0 lg:w-[250px] lg:self-start"
    >
      <div className="px-2 py-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t('sources.tableOfContents')}
      </div>
      <ScrollArea className="h-[50vh] lg:h-[70vh]">
        <div className="pr-3">
          {sections.map((section) => (
            <SectionRow
              key={section.id}
              section={section}
              depth={0}
              activeSectionId={activeSectionId}
              onSectionClick={onSectionClick}
              expandedIds={expandedIds}
              onToggle={handleToggle}
              untitledLabel={t('sources.untitledSection')}
              onSectionAction={onSectionAction}
              labels={actionLabels}
            />
          ))}
        </div>
      </ScrollArea>
    </nav>
  )
}
