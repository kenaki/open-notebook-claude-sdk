'use client'

import { MessageSquare } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { NotebookChatSession } from '@/lib/types/api'
import { EditableChatTitle, DeleteButton } from './ChatCard'
import { TagChips, TagEditor, type TagColorMap } from './TagEditor'

export function ChatRow({
  main,
  sideCount,
  newChatLabel,
  allTags,
  tagColors,
  relativeTime,
  onOpenMain,
  onDelete,
  onRename,
  onSaveTags,
  onTagClick,
  onSetTagColor,
  activeTags,
}: {
  main: NotebookChatSession
  sideCount: number
  newChatLabel: string
  allTags: string[]
  tagColors: TagColorMap
  relativeTime: (date: string) => string
  onOpenMain: () => void
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
    <li
      role="button"
      tabIndex={0}
      onClick={onOpenMain}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpenMain()
        }
      }}
      className="group flex cursor-pointer items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent-soft-2"
    >
      <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-accent-soft text-primary">
        <MessageSquare className="h-4 w-4" />
      </span>
      <EditableChatTitle
        title={main.title || ''}
        fallback={newChatLabel}
        subtitle={relativeTime(main.updated)}
        headingClass="text-sm font-medium text-foreground"
        onRename={onRename}
      />
      {tags.length > 0 && (
        <TagChips
          tags={tags}
          tagColors={tagColors}
          activeTags={activeTags}
          onTagClick={onTagClick}
          className="hidden max-w-[40%] md:flex"
        />
      )}
      {sideCount > 0 && (
        <span className="flex-shrink-0 text-[11px] text-text-3">
          {sideCount === 1
            ? t('gallery.oneSideChat')
            : t('gallery.sideChatCount').replace('{count}', sideCount.toString())}
        </span>
      )}
      <TagEditor
        tags={tags}
        allTags={allTags}
        tagColors={tagColors}
        onSave={onSaveTags}
        onSetTagColor={onSetTagColor}
      />
      <DeleteButton label={t('gallery.deleteChat')} onDelete={onDelete} />
    </li>
  )
}
