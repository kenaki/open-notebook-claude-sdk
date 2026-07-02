'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Sparkles, WandSparkles, StickyNote } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useNotebookWorkspace } from './NotebookWorkspaceProvider'
import { useCreateNote } from '@/lib/hooks/use-notes'

interface PendingSelection {
  parentId: string // the chat the selection came from (prospective sub-chat parent)
  quote: string // the selected text
  top: number // viewport y for the pill (selectionTop − 46)
  left: number // viewport x, centered over the selection
}

interface PassageSelectionMenuProps {
  // Spawn a sub-chat from the captured passage. Called on the "Chat about this" item.
  onChatAboutPassage: (parentId: string, quote: string) => void
}

const MIN_SELECTION_CHARS = 2
const PILL_OFFSET = 46

/**
 * Sub-chats / "chat about a passage" (Plan D / Chunk 11, extended by Document
 * Foundation C4). A single document-level selection watcher (mounted once on the
 * desktop notebook track). On `mouseup` it reads the current selection; if it's
 * ≥2 chars and lives inside an AI message body (an element tagged
 * `data-chat-scope={sessionId}`), it renders a floating action menu at the
 * selection. The menu offers:
 *   • Chat about this → spawns a sub-chat anchored to that parent + quote.
 *   • Explain → sends "Explain this passage: …" to the SAME chat session (the
 *     scope the selection came from), reusing the notebook chat dispatch.
 *   • Save note → creates a human Note with the selected text.
 * Dismisses on outside-click, scroll, or an empty selection. Annotations
 * (highlight rects / comment bubbles) are intentionally NOT built here — deferred
 * to Phase 4.
 */
export function PassageSelectionMenu({ onChatAboutPassage }: PassageSelectionMenuProps) {
  const { t } = useTranslation()
  const [pending, setPending] = useState<PendingSelection | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  // Chat dispatch + notebook id come from the workspace context this menu is
  // always mounted inside (Deep-Dive). `useNotebookWorkspace` returns null off a
  // notebook route, so Explain / Save-note degrade gracefully rather than throw.
  const workspace = useNotebookWorkspace()
  const createNote = useCreateNote()

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
      // Clicking the menu itself shouldn't dismiss it before its click fires.
      if (menuRef.current?.contains(e.target as Node)) return
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

  const finish = () => {
    window.getSelection()?.removeAllRanges()
    setPending(null)
  }

  const handleChat = () => {
    onChatAboutPassage(pending.parentId, pending.quote)
    finish()
  }

  const handleExplain = () => {
    // Reuse the notebook chat dispatch — send to the SAME session the selection
    // came from (parentId is a data-chat-scope session id), just a scoped prompt.
    void workspace?.chat.sendMessageTo(pending.parentId, `Explain this passage: ${pending.quote}`)
    finish()
  }

  const handleSaveNote = () => {
    const notebookId = workspace?.notebookId
    if (!notebookId) {
      toast.error(t('sources.cannotSaveNoteNoNotebook'))
      finish()
      return
    }
    createNote.mutate({
      content: pending.quote,
      note_type: 'human',
      notebook_id: notebookId,
    })
    finish()
  }

  const itemClass =
    'flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-popover-foreground hover:bg-muted transition-colors whitespace-nowrap'

  return createPortal(
    <div
      ref={menuRef}
      // Keep the text selection (and these buttons) alive through the click.
      onMouseDown={(e) => e.preventDefault()}
      style={{ position: 'fixed', top: pending.top, left: pending.left, transform: 'translateX(-50%)', zIndex: 60 }}
      className="flex items-center gap-0.5 rounded-lg border border-border bg-popover p-1 shadow-[var(--shadow)]"
    >
      <button type="button" onClick={handleChat} className={itemClass}>
        <Sparkles className="h-3.5 w-3.5" />
        {t('chat.chatAboutThis')}
      </button>
      <button type="button" onClick={handleExplain} className={itemClass}>
        <WandSparkles className="h-3.5 w-3.5" />
        {t('chat.explain')}
      </button>
      <button type="button" onClick={handleSaveNote} className={itemClass}>
        <StickyNote className="h-3.5 w-3.5" />
        {t('chat.saveNote')}
      </button>
    </div>,
    document.body
  )
}
