'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Sparkles } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'

interface PendingSelection {
  parentId: string // the chat the selection came from (prospective sub-chat parent)
  quote: string // the selected text
  top: number // viewport y for the pill (selectionTop − 46)
  left: number // viewport x, centered over the selection
}

interface PassageSelectionMenuProps {
  // Spawn a sub-chat from the captured passage. Called on pill click.
  onChatAboutPassage: (parentId: string, quote: string) => void
}

const MIN_SELECTION_CHARS = 2
const PILL_OFFSET = 46

/**
 * Sub-chats / "chat about a passage" (Plan D / Chunk 11). A single document-level
 * selection watcher (mounted once on the desktop notebook track). On `mouseup` it
 * reads the current selection; if it's ≥2 chars and lives inside an AI message
 * body (an element tagged `data-chat-scope={sessionId}`), it renders a floating
 * accent pill at the selection. Clicking the pill spawns a sub-chat anchored to
 * that parent + quote. Dismisses on outside-click, scroll, or an empty selection.
 */
export function PassageSelectionMenu({ onChatAboutPassage }: PassageSelectionMenuProps) {
  const { t } = useTranslation()
  const [pending, setPending] = useState<PendingSelection | null>(null)
  const pillRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const dismiss = () => setPending(null)

    const handleMouseUp = () => {
      const selection = window.getSelection()
      if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
        setPending(null)
        return
      }
      const quote = selection.toString().trim()
      if (quote.length < MIN_SELECTION_CHARS) {
        setPending(null)
        return
      }
      const range = selection.getRangeAt(0)
      const container = range.commonAncestorContainer
      const el = container instanceof Element ? container : container.parentElement
      const scope = el?.closest<HTMLElement>('[data-chat-scope]')
      const parentId = scope?.dataset.chatScope
      if (!parentId) {
        // Selection isn't inside an AI message body → not a sub-chat candidate.
        setPending(null)
        return
      }
      const rect = range.getBoundingClientRect()
      setPending({
        parentId,
        quote,
        top: rect.top - PILL_OFFSET,
        left: rect.left + rect.width / 2,
      })
    }

    const handleMouseDown = (e: MouseEvent) => {
      // Clicking the pill itself shouldn't dismiss it before its click fires.
      if (pillRef.current?.contains(e.target as Node)) return
      setPending(null)
    }

    document.addEventListener('mouseup', handleMouseUp)
    document.addEventListener('mousedown', handleMouseDown)
    // Capture-phase scroll so we also catch scrolling inside the panel track.
    window.addEventListener('scroll', dismiss, true)
    return () => {
      document.removeEventListener('mouseup', handleMouseUp)
      document.removeEventListener('mousedown', handleMouseDown)
      window.removeEventListener('scroll', dismiss, true)
    }
  }, [])

  if (!pending || typeof document === 'undefined') return null

  const handleClick = () => {
    onChatAboutPassage(pending.parentId, pending.quote)
    window.getSelection()?.removeAllRanges()
    setPending(null)
  }

  return createPortal(
    <button
      ref={pillRef}
      type="button"
      // Keep the text selection (and this button) alive through the click.
      onMouseDown={(e) => e.preventDefault()}
      onClick={handleClick}
      style={{ position: 'fixed', top: pending.top, left: pending.left, transform: 'translateX(-50%)', zIndex: 60 }}
      className="flex items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground shadow-[var(--shadow)] hover:opacity-90 transition-opacity"
    >
      <Sparkles className="h-3.5 w-3.5" />
      {t('chat.chatAboutThis')}
    </button>,
    document.body
  )
}
