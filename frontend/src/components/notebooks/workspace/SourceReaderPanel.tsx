'use client'

import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SourceDetailContent } from '@/components/source/detail/SourceDetailContent'
import { useTranslation } from '@/lib/hooks/use-translation'

interface SourceReaderPanelProps {
  /** Full source record id (the panel token, e.g. "source:abc123"). */
  sourceId: string
  onClose: () => void
}

/**
 * Thin wrapper mounting the full source reader (tabs, annotations, highlighting,
 * PDF view) as a workspace track panel (cross-interface-study / Chunk A1).
 * Reuses `SourceDetailContent` as-is — no fork — in its `toolbar` layout, which
 * collapses the header into one line so the reader gets the rest of the height;
 * `PanelCard` already supplies the bounded-height flex parent it needs.
 *
 * Ask-AI wiring (`onChatAboutHighlight`/`onChatAboutHighlights`) lands in
 * Chunk A3 — until then those buttons stay hidden (the props are simply
 * omitted here, and `SourceDetailContent` hides them when absent).
 */
export function SourceReaderPanel({ sourceId, onClose }: SourceReaderPanelProps) {
  const { t } = useTranslation()
  return (
    <SourceDetailContent
      sourceId={sourceId}
      layout="toolbar"
      onClose={onClose}
      toolbarTrailing={
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          title={t('common.close')}
          aria-label={t('common.close')}
        >
          <X className="h-4 w-4" />
        </Button>
      }
    />
  )
}
