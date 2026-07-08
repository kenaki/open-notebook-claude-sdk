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
 * parse header's `section_index` (every heading block, in document order).
 * Selecting an entry jumps to its heading (`onJump(seq)` — the caller loads
 * the containing span if it isn't in view yet, then scrolls to `data-seq`).
 */
export function ReaderOutline({
  sections,
  onJump,
}: {
  sections: SectionIndexEntry[]
  onJump: (seq: number) => void
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
      <DropdownMenuContent align="start" className="max-h-96 w-72 overflow-y-auto">
        {sections.map((entry) => (
          <DropdownMenuItem
            key={entry.seq}
            onClick={() => onJump(entry.seq)}
            style={{ paddingLeft: `${0.5 + Math.max(0, entry.level - 1) * 0.9}rem` }}
            className="truncate"
          >
            <span className="truncate">{entry.title || t('sources.reader.untitledSection')}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
