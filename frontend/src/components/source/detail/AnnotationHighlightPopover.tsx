'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Plus, Sparkles, StickyNote, Tag as TagIcon, Trash2, X } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { cn } from '@/lib/utils'
import { resolveTagColorKey, tagColorStyle } from '@/lib/utils/tag-colors'
import type { Annotation } from '@/lib/types/api'

/**
 * Fixed starter tags offered as one-click quick-adds (hybrid model: freeform
 * storage, seeded suggestions). Canonical English strings, deliberately NOT
 * localized — the stored tag value must stay stable across UI languages so the
 * vocabulary doesn't fragment.
 */
export const STARTER_TAGS = ['Important', 'Question', 'Definition', 'Todo'] as const

/**
 * Highlight color system: five named colors shared by the selection toolbar
 * (pick a color to create), the highlight popover (re-color) and the sidebar
 * (filter). Names are i18n keys so tooltips/aria-labels localize; the hex
 * values are stored on the annotation, so they must stay stable.
 */
export const HIGHLIGHT_PALETTE = [
  { value: '#fde047', nameKey: 'sources.annotations.colorYellow' },
  { value: '#86efac', nameKey: 'sources.annotations.colorGreen' },
  { value: '#93c5fd', nameKey: 'sources.annotations.colorBlue' },
  { value: '#fca5a5', nameKey: 'sources.annotations.colorPink' },
  { value: '#d8b4fe', nameKey: 'sources.annotations.colorPurple' },
] as const

export const DEFAULT_HIGHLIGHT_COLOR = HIGHLIGHT_PALETTE[0].value

/**
 * Row of color swatches. The selected swatch gets a foreground ring; hover
 * scales the dot so the row reads as tappable.
 */
export function ColorDots({
  selected,
  onPick,
  size = 'md',
}: {
  selected?: string
  onPick: (color: string) => void
  size?: 'sm' | 'md'
}) {
  const { t } = useTranslation()
  const dot = size === 'sm' ? 'h-4 w-4' : 'h-5 w-5'
  return (
    <div className="flex items-center gap-1.5">
      {HIGHLIGHT_PALETTE.map(({ value, nameKey }) => (
        <button
          key={value}
          type="button"
          title={t(nameKey)}
          aria-label={t(nameKey)}
          onClick={() => onPick(value)}
          className={`${dot} rounded-full transition-transform hover:scale-110 ${
            selected === value ? 'ring-2 ring-foreground ring-offset-1 ring-offset-popover' : ''
          }`}
          style={{ backgroundColor: value }}
        />
      ))}
    </div>
  )
}

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
  /** Replace this highlight's whole tag list (whole-list replacement). */
  onSaveTags: (tags: string[]) => void
  /** Tags already used on other highlights in this doc — quick-add suggestions. */
  allTags: string[]
  /** Open with the note editor expanded + focused (selection-toolbar "Note"). */
  startInNoteMode?: boolean
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
  onSaveTags,
  allTags,
  startInNoteMode = false,
}: AnnotationHighlightPopoverProps) {
  const { t } = useTranslation()
  const [note, setNote] = useState(annotation.note ?? '')
  const [tagDraft, setTagDraft] = useState('')

  const addTag = (raw: string) => {
    const value = raw.trim()
    if (!value) return
    // Case-insensitive dedupe against the current set.
    if (annotation.tags.some((tg) => tg.toLowerCase() === value.toLowerCase())) {
      setTagDraft('')
      return
    }
    onSaveTags([...annotation.tags, value])
    setTagDraft('')
  }
  const removeTag = (tag: string) => {
    onSaveTags(annotation.tags.filter((tg) => tg !== tag))
  }
  // Starters ∪ tags-used-elsewhere, deduped case-insensitively, minus applied.
  const suggestions = [...STARTER_TAGS, ...allTags].filter(
    (tag, i, arr) =>
      arr.findIndex((x) => x.toLowerCase() === tag.toLowerCase()) === i &&
      !annotation.tags.some((tg) => tg.toLowerCase() === tag.toLowerCase())
  )
  // Note editor is collapsed behind an "Add note" button unless the highlight
  // already has a note or the caller asked for note mode.
  const [noteMode, setNoteMode] = useState(startInNoteMode || !!annotation.note)
  const popoverRef = useRef<HTMLDivElement>(null)
  const noteRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const handleMouseDown = (e: MouseEvent) => {
      if (popoverRef.current?.contains(e.target as Node)) return
      onClose()
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [onClose])

  useEffect(() => {
    if (noteMode) noteRef.current?.focus()
  }, [noteMode])

  if (typeof document === 'undefined') return null

  const noteChanged = note !== (annotation.note ?? '')
  // Keep the popover on-screen when the highlight sits near the viewport edge.
  const clampedLeft = Math.min(left, window.innerWidth - 300)
  const clampedTop = Math.min(top, window.innerHeight - 280)

  return createPortal(
    <div
      ref={popoverRef}
      style={{ position: 'fixed', top: clampedTop, left: clampedLeft, zIndex: 60 }}
      className="w-72 space-y-2 rounded-lg border border-border bg-popover p-2.5 shadow-[var(--shadow)]"
    >
      <div className="flex items-start gap-2">
        {annotation.quote ? (
          <p
            className="line-clamp-3 min-w-0 flex-1 border-l-2 pl-2 text-xs italic text-muted-foreground"
            style={{ borderColor: annotation.color }}
          >
            {annotation.quote}
          </p>
        ) : (
          <span className="flex-1" />
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label={t('sources.annotations.close')}
          className="flex-shrink-0 rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <ColorDots selected={annotation.color} onPick={onChangeColor} />

      {/* Tags: colored chips (auto-color from the tag text), a freeform input
          (Enter to add), and quick-add suggestions (starters + doc tags). */}
      <div className="space-y-1.5">
        {annotation.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {annotation.tags.map((tag) => {
              const style = tagColorStyle(resolveTagColorKey(tag, {}))
              return (
                <span
                  key={tag}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-full py-0.5 pl-2 pr-1 text-[11px]',
                    style.chip
                  )}
                >
                  <span className="max-w-[8rem] truncate">{tag}</span>
                  <button
                    type="button"
                    aria-label={`${t('common.delete')} ${tag}`}
                    onClick={() => removeTag(tag)}
                    className="rounded-full hover:text-foreground"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </span>
              )
            })}
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <TagIcon className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden="true" />
          <input
            value={tagDraft}
            onChange={(e) => setTagDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                addTag(tagDraft)
              }
            }}
            placeholder={t('sources.annotations.tagInputPlaceholder')}
            aria-label={t('sources.annotations.editTags')}
            className="h-6 min-w-0 flex-1 rounded-sm border border-border bg-background px-1.5 text-xs"
          />
        </div>
        {suggestions.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {suggestions.map((tag) => (
              <button
                key={tag}
                type="button"
                onClick={() => addTag(tag)}
                className="inline-flex items-center gap-0.5 rounded-full border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <Plus className="h-2.5 w-2.5" />
                {tag}
              </button>
            ))}
          </div>
        )}
      </div>

      {noteMode ? (
        <div className="space-y-1">
          <textarea
            ref={noteRef}
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
      ) : (
        <button
          type="button"
          onClick={() => setNoteMode(true)}
          className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <StickyNote className="h-3.5 w-3.5" />
          {t('sources.annotations.addNote')}
        </button>
      )}

      <div className="flex items-center justify-between border-t border-border pt-2">
        {onChatAboutHighlight && annotation.quote ? (
          <button
            type="button"
            onClick={() => onChatAboutHighlight(annotation.quote as string)}
            className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-accent-soft"
          >
            <Sparkles className="h-3.5 w-3.5" />
            {t('sources.annotations.askAi')}
          </button>
        ) : (
          <span />
        )}
        <button
          type="button"
          onClick={onDelete}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-destructive transition-colors hover:bg-destructive/10"
        >
          <Trash2 className="h-3.5 w-3.5" />
          {t('common.delete')}
        </button>
      </div>
    </div>,
    document.body
  )
}
