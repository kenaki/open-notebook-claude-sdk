'use client'

import { List } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { SectionIndexEntry } from '@/lib/types/api'

/**
 * pdf-block-ingestion Track D6 — outline nav for the reader, sourced from the
 * parse header's `section_index`: the PDF's TOC bookmarks aligned onto heading
 * blocks, with non-TOC headings nested beneath (to-fix/006). Falls back to a
 * flat, junk-filtered heading list when the PDF carries no bookmarks.
 * Selecting an entry jumps to its heading (`onJump(seq)` — the caller loads
 * the containing span if it isn't in view yet, then scrolls to `data-seq`).
 *
 * `pageOfSeq` resolves each heading's page from the parse header's `page_index`.
 * It returns null for a source parsed before pages were indexed, in which case
 * the entry simply renders without a page number.
 */
export function ReaderOutline({
  sections,
  onJump,
  pageOfSeq,
}: {
  sections: SectionIndexEntry[]
  onJump: (seq: number) => void
  pageOfSeq?: (seq: number) => number | null
}) {
  const { t } = useTranslation()
  if (sections.length === 0) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <List className="h-3.5 w-3.5" aria-hidden="true" />
          {t('sources.reader.outline')}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-96 w-80 overflow-y-auto">
        {sections.map((entry) => {
          const page = pageOfSeq?.(entry.seq) ?? null
          return (
            <DropdownMenuItem
              key={entry.seq}
              onClick={() => onJump(entry.seq)}
              // Levels run 1–6 (to-fix/006). Cap the indent at 4 so a deep
              // entry keeps a usable title width inside the w-80 dropdown.
              style={{
                paddingLeft: `${0.5 + Math.min(Math.max(entry.level - 1, 0), 3) * 0.75}rem`,
              }}
              className="flex items-center gap-2"
            >
              <span className="min-w-0 flex-1 truncate">
                {entry.title || t('sources.reader.untitledSection')}
              </span>
              {page != null && (
                <span className="flex-shrink-0 text-[10px] tabular-nums text-muted-foreground">
                  {page}
                </span>
              )}
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
