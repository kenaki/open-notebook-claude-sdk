'use client'

import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Sparkles, StickyNote } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import {
  ColorDots,
  DEFAULT_HIGHLIGHT_COLOR,
} from '@/components/source/detail/AnnotationHighlightPopover'

/**
 * pdf-block-ingestion Track D7 — the reader's selection toolbar, mirroring the
 * PDFViewer highlight target toolbar (pick a color to highlight, add with a
 * note, or Ask AI). Rendered via a portal at a fixed viewport position so it
 * floats above the reader without disturbing its scroll container. Dismisses on
 * an outside click (a fresh selection replaces it).
 */
export function ReaderSelectionToolbar({
  top,
  left,
  onPickColor,
  onNote,
  onAskAi,
  onClose,
}: {
  top: number
  left: number
  onPickColor: (color: string) => void
  onNote: () => void
  onAskAi?: () => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleMouseDown = (e: MouseEvent) => {
      if (ref.current?.contains(e.target as Node)) return
      onClose()
    }
    // Defer so the mouseup that opened this toolbar doesn't immediately close it.
    const id = window.setTimeout(
      () => document.addEventListener('mousedown', handleMouseDown),
      0
    )
    return () => {
      window.clearTimeout(id)
      document.removeEventListener('mousedown', handleMouseDown)
    }
  }, [onClose])

  if (typeof document === 'undefined') return null

  const clampedLeft = Math.min(left, window.innerWidth - 260)
  const clampedTop = Math.min(top, window.innerHeight - 60)

  return createPortal(
    <div
      ref={ref}
      style={{ position: 'fixed', top: clampedTop, left: clampedLeft, zIndex: 60 }}
    >
      <div
        role="toolbar"
        aria-label={t('sources.annotations.addHighlight')}
        className="flex items-center gap-2 rounded-lg border border-border bg-popover px-2.5 py-1.5 shadow-[var(--shadow)]"
      >
        <ColorDots size="sm" selected={DEFAULT_HIGHLIGHT_COLOR} onPick={onPickColor} />
        <span className="h-4 w-px bg-border" aria-hidden="true" />
        <button
          type="button"
          className="flex items-center gap-1 text-xs font-medium text-popover-foreground hover:text-primary"
          onClick={onNote}
        >
          <StickyNote className="h-3.5 w-3.5" aria-hidden="true" />
          {t('sources.annotations.addNote')}
        </button>
        {onAskAi && (
          <button
            type="button"
            className="flex items-center gap-1 text-xs font-medium text-primary hover:opacity-80"
            onClick={onAskAi}
          >
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            {t('sources.annotations.askAi')}
          </button>
        )}
      </div>
    </div>,
    document.body
  )
}
