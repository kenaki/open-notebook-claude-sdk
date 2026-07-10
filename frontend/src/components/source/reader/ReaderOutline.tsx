'use client'

import { useCallback, useMemo, useState } from 'react'
import { ChevronRight, List } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useTranslation } from '@/lib/hooks/use-translation'
import { cn } from '@/lib/utils'
import type { SectionIndexEntry } from '@/lib/types/api'

/**
 * pdf-block-ingestion Track D6 — outline nav for the reader, sourced from the
 * parse header's `section_index`: the PDF's TOC bookmarks aligned onto heading
 * blocks, with non-TOC headings nested beneath (to-fix/006). Falls back to a
 * flat, junk-filtered heading list when the PDF carries no bookmarks.
 * Selecting an entry jumps to its heading (`onJump(seq)` — the caller loads
 * the containing span if it isn't in view yet, then scrolls to `data-seq`).
 *
 * `section_index` is flat but hierarchical: `level` encodes depth, so the rows
 * are re-nested into a collapsible tree. A chapter's title jumps; its chevron
 * expands the sections beneath it without leaving the outline. This is a
 * Popover rather than a DropdownMenu precisely because `DropdownMenuItem`
 * closes the menu on click — a chevron inside one would dismiss the outline
 * before you could reach the section it just revealed.
 *
 * `pageOfSeq` resolves each heading's page from the parse header's `page_index`.
 * It returns null for a source parsed before pages were indexed, in which case
 * the entry simply renders without a page number.
 */

/** Indent caps out here so a deep entry keeps a usable title width in `w-80`. */
const MAX_INDENT_DEPTH = 3

export type OutlineNode = SectionIndexEntry & { children: OutlineNode[] }

/**
 * Re-nest the flat, seq-ordered `section_index` using each entry's `level`.
 * An entry whose level doesn't sit under any open ancestor (a level-2 heading
 * before the first chapter, say) becomes a root rather than being dropped.
 */
export function buildOutlineTree(sections: SectionIndexEntry[]): OutlineNode[] {
  const roots: OutlineNode[] = []
  const ancestors: OutlineNode[] = []

  for (const entry of sections) {
    const node: OutlineNode = { ...entry, children: [] }
    while (ancestors.length > 0 && ancestors[ancestors.length - 1].level >= node.level) {
      ancestors.pop()
    }
    if (ancestors.length > 0) ancestors[ancestors.length - 1].children.push(node)
    else roots.push(node)
    ancestors.push(node)
  }
  return roots
}

/**
 * The last chapter that starts at or before `currentPage` — the one being read.
 * Null when pages aren't indexed for this parse, which just means no chapter is
 * pre-expanded. Roots arrive in seq order, so the last match wins.
 */
function activeChapterSeq(
  roots: OutlineNode[],
  currentPage: number | null | undefined,
  pageOfSeq: ((seq: number) => number | null) | undefined
): number | null {
  if (currentPage == null || !pageOfSeq) return null
  let active: number | null = null
  for (const root of roots) {
    const page = pageOfSeq(root.seq)
    if (page != null && page <= currentPage) active = root.seq
  }
  return active
}

function OutlineRow({
  node,
  depth,
  expanded,
  activeSeq,
  onToggle,
  onSelect,
  pageOfSeq,
}: {
  node: OutlineNode
  depth: number
  expanded: Set<number>
  activeSeq: number | null
  onToggle: (seq: number) => void
  onSelect: (seq: number) => void
  pageOfSeq?: (seq: number) => number | null
}) {
  const { t } = useTranslation()
  const hasChildren = node.children.length > 0
  const isExpanded = expanded.has(node.seq)
  const isActive = node.seq === activeSeq
  const page = pageOfSeq?.(node.seq) ?? null

  return (
    <li
      role="treeitem"
      aria-selected={isActive}
      aria-expanded={hasChildren ? isExpanded : undefined}
    >
      <div
        className="flex items-center rounded-sm hover:bg-accent hover:text-accent-foreground"
        style={{ paddingLeft: `${Math.min(depth, MAX_INDENT_DEPTH) * 0.75}rem` }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={() => onToggle(node.seq)}
            aria-expanded={isExpanded}
            aria-label={
              isExpanded
                ? t('sources.reader.collapseSection')
                : t('sources.reader.expandSection')
            }
            className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
          >
            <ChevronRight
              className={cn('h-3.5 w-3.5 transition-transform', isExpanded && 'rotate-90')}
              aria-hidden="true"
            />
          </button>
        ) : (
          <span className="h-6 w-6 flex-shrink-0" aria-hidden="true" />
        )}
        <button
          type="button"
          onClick={() => onSelect(node.seq)}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-sm py-1.5 pr-2 text-left text-sm focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
        >
          <span className={cn('min-w-0 flex-1 truncate', isActive && 'font-medium')}>
            {node.title || t('sources.reader.untitledSection')}
          </span>
          {page != null && (
            <span className="flex-shrink-0 text-[10px] tabular-nums text-muted-foreground">
              {page}
            </span>
          )}
        </button>
      </div>
      {hasChildren && isExpanded && (
        <ul role="group">
          {node.children.map((child, i) => (
            <OutlineRow
              key={`${child.seq}-${i}`}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              activeSeq={activeSeq}
              onToggle={onToggle}
              onSelect={onSelect}
              pageOfSeq={pageOfSeq}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

export function ReaderOutline({
  sections,
  onJump,
  pageOfSeq,
  currentPage,
}: {
  sections: SectionIndexEntry[]
  onJump: (seq: number) => void
  pageOfSeq?: (seq: number) => number | null
  currentPage?: number | null
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const tree = useMemo(() => buildOutlineTree(sections), [sections])
  const activeSeq = useMemo(
    () => activeChapterSeq(tree, currentPage, pageOfSeq),
    [tree, currentPage, pageOfSeq]
  )

  const handleOpenChange = useCallback(
    (next: boolean) => {
      setOpen(next)
      // Reopening re-seeds the expansion from where the reader actually is,
      // so the outline points at the current chapter instead of restoring a
      // stale set of toggles from wherever the user was reading before.
      if (next) setExpanded(activeSeq == null ? new Set() : new Set([activeSeq]))
    },
    [activeSeq]
  )

  const handleToggle = useCallback((seq: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (!next.delete(seq)) next.add(seq)
      return next
    })
  }, [])

  const handleSelect = useCallback(
    (seq: number) => {
      setOpen(false)
      onJump(seq)
    },
    [onJump]
  )

  if (sections.length === 0) return null

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <List className="h-3.5 w-3.5" aria-hidden="true" />
          {t('sources.reader.outline')}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="max-h-96 w-80 overflow-y-auto p-1">
        <ul role="tree" aria-label={t('sources.reader.outline')}>
          {tree.map((node, i) => (
            <OutlineRow
              key={`${node.seq}-${i}`}
              node={node}
              depth={0}
              expanded={expanded}
              activeSeq={activeSeq}
              onToggle={handleToggle}
              onSelect={handleSelect}
              pageOfSeq={pageOfSeq}
            />
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
