'use client'

import { useRef, useState } from 'react'
import { CornerDownRight, MessageSquare, Pencil, Trash2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { NotebookChatSession } from '@/lib/types/api'
import { TagChips, TagEditor, type TagColorMap } from './TagEditor'

// Inline-rename chat title for a gallery card/row. A hover/focus pencil turns
// the heading into a text field; Enter or blur commits, Escape cancels. Every
// handler stops propagation so editing never triggers the parent's navigate-on-click.
export function EditableChatTitle({
  title,
  fallback,
  subtitle,
  headingClass,
  onRename,
}: {
  title: string
  fallback: string
  subtitle: string
  headingClass: string
  onRename: (title: string) => void
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(title)
  // Guard against the Enter-then-blur double commit (both fire onRename).
  const committed = useRef(false)

  const startEdit = (e: React.MouseEvent) => {
    e.stopPropagation()
    committed.current = false
    setDraft(title)
    setEditing(true)
  }
  const commit = () => {
    if (committed.current) return
    committed.current = true
    setEditing(false)
    const trimmed = draft.trim()
    if (trimmed && trimmed !== title) onRename(trimmed)
  }
  const cancel = () => {
    committed.current = true
    setEditing(false)
    setDraft(title)
  }

  if (editing) {
    return (
      <div className="min-w-0 flex-1" onClick={(e) => e.stopPropagation()}>
        <Input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onFocus={(e) => e.target.select()}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            e.stopPropagation()
            if (e.key === 'Enter') {
              e.preventDefault()
              commit()
            } else if (e.key === 'Escape') {
              e.preventDefault()
              cancel()
            }
          }}
          onBlur={commit}
          placeholder={t('chat.sessionTitlePlaceholder')}
          aria-label={t('chat.renameChat')}
          className="h-7 text-sm"
        />
      </div>
    )
  }

  return (
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-1">
        <h3 className={cn('truncate', headingClass)}>{title || fallback}</h3>
        <button
          type="button"
          onClick={startEdit}
          aria-label={t('chat.renameChat')}
          title={t('chat.renameChat')}
          className="flex-shrink-0 text-text-3 opacity-0 transition-opacity hover:text-foreground focus:outline-none focus-visible:opacity-100 group-hover:opacity-100"
        >
          <Pencil className="h-3 w-3" />
        </button>
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
    </div>
  )
}

// Hover-revealed delete affordance shared by card + row. stopPropagation keeps
// the click from bubbling to the parent's "open chat" handler.
export function DeleteButton({ label, onDelete }: { label: string; onDelete: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={(e) => {
        e.stopPropagation()
        onDelete()
      }}
      className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md text-text-3 opacity-0 transition-all hover:bg-destructive/10 hover:text-destructive focus:outline-none focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent-soft-2 group-hover:opacity-100"
    >
      <Trash2 className="h-4 w-4" />
    </button>
  )
}

export function ChatCard({
  main,
  sideChats,
  newChatLabel,
  allTags,
  tagColors,
  relativeTime,
  onOpenMain,
  onOpenSide,
  onDelete,
  onRename,
  onSaveTags,
  onTagClick,
  onSetTagColor,
  activeTags,
}: {
  main: NotebookChatSession
  sideChats: NotebookChatSession[]
  newChatLabel: string
  allTags: string[]
  tagColors: TagColorMap
  relativeTime: (date: string) => string
  onOpenMain: () => void
  onOpenSide: (sideId: string) => void
  onDelete: () => void
  onRename: (title: string) => void
  onSaveTags: (tags: string[]) => void
  onTagClick: (tag: string) => void
  onSetTagColor: (tag: string, colorKey: string) => void
  activeTags: string[]
}) {
  const { t } = useTranslation()
  const tags = main.tags ?? []
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpenMain}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpenMain()
        }
      }}
      className="group relative flex cursor-pointer flex-col rounded-xl border border-border bg-card p-4 text-left shadow-[var(--shadow)] transition-all duration-200 hover:-translate-y-0.5 hover:border-primary-soft-border hover:shadow-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-soft-2"
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-accent-soft text-primary">
          <MessageSquare className="h-4 w-4" />
        </span>
        <EditableChatTitle
          title={main.title || ''}
          fallback={newChatLabel}
          subtitle={relativeTime(main.updated)}
          headingClass="text-sm font-semibold text-foreground"
          onRename={onRename}
        />
        <TagEditor
          tags={tags}
          allTags={allTags}
          tagColors={tagColors}
          onSave={onSaveTags}
          onSetTagColor={onSetTagColor}
        />
        <DeleteButton label={t('gallery.deleteChat')} onDelete={onDelete} />
      </div>

      {tags.length > 0 && (
        <TagChips
          tags={tags}
          tagColors={tagColors}
          activeTags={activeTags}
          onTagClick={onTagClick}
          className="mt-3"
        />
      )}

      {/* Nested side chats — subtle, so the hierarchy reads at a glance. */}
      {sideChats.length > 0 && (
        <ul className="mt-3 space-y-0.5 border-t border-border-2 pt-2.5">
          {sideChats.map((side) => (
            <li key={side.id}>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onOpenSide(side.id)
                }}
                className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <CornerDownRight className="h-3 w-3 flex-shrink-0 text-text-3" />
                <span className="truncate">{side.title || newChatLabel}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex items-center gap-3 text-[11px] text-text-3">
        <span>
          {sideChats.length === 1
            ? t('gallery.oneSideChat')
            : t('gallery.sideChatCount').replace('{count}', sideChats.length.toString())}
        </span>
      </div>
    </div>
  )
}
