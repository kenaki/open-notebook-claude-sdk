'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MessageSquare, Trash2 } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { Annotation } from '@/lib/types/api'

export const HIGHLIGHT_COLORS = ['#fde047', '#86efac', '#93c5fd', '#fca5a5', '#d8b4fe']

interface AnnotationHighlightPopoverProps {
  annotation: Annotation
  top: number
  left: number
  onClose: () => void
  onSaveNote: (note: string) => void
  onChangeColor: (color: string) => void
  onDelete: () => void
  /**
   * Reuses the "chat about this passage" ACTION from PassageSelectionMenu
   * (send the quote into the active chat) — not the floating-pill component
   * itself, which is scoped to `data-chat-scope` chat bubbles and doesn't
   * apply inside the PDF viewer. Undefined where no chat is wired (e.g. the
   * source modal) — the button is hidden there.
   */
  onChatAboutHighlight?: (quote: string) => void
}

/**
 * Popup shown when clicking an existing highlight overlay in the PDFViewer.
 * Rendered via a portal so it lives outside the pdf.js page-layer tree —
 * its own state (note draft, hover) never touches the PDFViewer/highlight
 * plugin instances, so typing here can't trigger a costly PDF re-layout.
 */
export function AnnotationHighlightPopover({
  annotation,
  top,
  left,
  onClose,
  onSaveNote,
  onChangeColor,
  onDelete,
  onChatAboutHighlight,
}: AnnotationHighlightPopoverProps) {
  const { t } = useTranslation()
  const [note, setNote] = useState(annotation.note ?? '')
  const popoverRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleMouseDown = (e: MouseEvent) => {
      if (popoverRef.current?.contains(e.target as Node)) return
      onClose()
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [onClose])

  if (typeof document === 'undefined') return null

  const noteChanged = note !== (annotation.note ?? '')

  return createPortal(
    <div
      ref={popoverRef}
      style={{ position: 'fixed', top, left, zIndex: 60 }}
      className="w-64 space-y-2 rounded-lg border border-border bg-popover p-2 shadow-[var(--shadow)]"
    >
      {annotation.quote && (
        <p
          className="line-clamp-3 border-l-2 pl-2 text-xs italic text-muted-foreground"
          style={{ borderColor: annotation.color }}
        >
          {annotation.quote}
        </p>
      )}

      <div className="flex items-center gap-1">
        {HIGHLIGHT_COLORS.map((color) => (
          <button
            key={color}
            type="button"
            aria-label={color}
            onClick={() => onChangeColor(color)}
            className="h-5 w-5 rounded-full border-2"
            style={{
              backgroundColor: color,
              borderColor: annotation.color === color ? 'var(--foreground)' : 'transparent',
            }}
          />
        ))}
      </div>

      <div className="space-y-1">
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={t('sources.annotations.notePlaceholder')}
          className="h-16 w-full resize-none rounded-sm border border-border bg-background p-1.5 text-xs"
        />
        {noteChanged && (
          <button
            type="button"
            onClick={() => onSaveNote(note)}
            className="rounded-sm bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground hover:opacity-90"
          >
            {t('common.save')}
          </button>
        )}
      </div>

      <div className="flex items-center justify-between pt-1">
        <button
          type="button"
          onClick={onDelete}
          className="flex items-center gap-1 text-xs text-destructive hover:opacity-80"
        >
          <Trash2 className="h-3.5 w-3.5" />
          {t('common.delete')}
        </button>
        <div className="flex items-center gap-2">
          {onChatAboutHighlight && annotation.quote && (
            <button
              type="button"
              onClick={() => onChatAboutHighlight(annotation.quote as string)}
              className="flex items-center gap-1 text-xs font-medium hover:text-primary"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              {t('chat.chatAboutThis')}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            {t('sources.annotations.close')}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}
