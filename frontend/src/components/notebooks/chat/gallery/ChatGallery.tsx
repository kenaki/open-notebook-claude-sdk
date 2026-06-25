'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Layers,
  LayoutGrid,
  List as ListIcon,
  MessageSquare,
  Plus,
  Search,
  X,
} from 'lucide-react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/hooks/use-translation'
import { EmptyState } from '@/components/common/EmptyState'
import { useNotebookWorkspaceStrict } from '@/components/notebooks/workspace/NotebookWorkspaceProvider'
import {
  useChatGalleryViewStore,
  type ChatGalleryViewMode,
} from '@/lib/stores/chat-gallery-view-store'
import { resolveTagColorKey, tagColorStyle } from '@/lib/utils/tag-colors'
import { formatRelative } from '@/lib/utils/format'
import type { NotebookChatSession } from '@/lib/types/api'
import { useChatFiltering } from './useChatFiltering'
import { ChatCard } from './ChatCard'
import { ChatRow } from './ChatRow'
import { EditableTagChip } from './TagEditor'

/**
 * Notebook Chat Gallery: past Main Chats as a card grid or compact list (toggle
 * persisted per-browser). Search + tag filters; group-by-tag sectioning. Each
 * card surfaces nested Side Chats. Cards enter the Dual-Panel Deep Dive;
 * "Start New Main Chat" spins one up immediately.
 */
export function ChatGallery() {
  const { t, language } = useTranslation()
  const router = useRouter()
  const { notebookId, chat, tagColors, setTagColor, renameTag } = useNotebookWorkspaceStrict()
  const viewMode = useChatGalleryViewStore((s) => s.viewMode)
  const setViewMode = useChatGalleryViewStore((s) => s.setViewMode)
  // Main chat queued for deletion (drives the confirmation dialog).
  const [pendingDelete, setPendingDelete] = useState<NotebookChatSession | null>(null)

  const newChatLabel = t('chat.newChat')
  const mains = chat.mainSessions

  const {
    query,
    setQuery,
    activeTags,
    groupByTag,
    setGroupByTag,
    allTags,
    filteredMains,
    groups,
    toggleTagFilter,
    handleRenameTag,
    filtersActive,
    clearFilters,
  } = useChatFiltering(mains, newChatLabel, renameTag)

  const relativeTime = (d: string) => formatRelative(d, language)

  const enterChat = (chatId: string) => {
    router.push(`/notebooks/${notebookId}/chat/${chatId}`)
  }

  // Optimistic spawn: a temp card lands in the list and we jump straight into
  // the Deep-Dive at the temp id, then reconcile the URL to the real session
  // once it lands (or fall back to the gallery if creation failed).
  const startNewMainChat = () => {
    const { tempId, promise } = chat.createMainChat(newChatLabel)
    enterChat(tempId)
    promise.then((session) => {
      router.replace(
        session
          ? `/notebooks/${notebookId}/chat/${session.id}`
          : `/notebooks/${notebookId}`
      )
    })
  }

  const confirmDelete = () => {
    if (!pendingDelete) return
    chat.deleteSession(pendingDelete.id)
    setPendingDelete(null)
  }

  // Render a set of chats in the current view mode (reused by the flat view and
  // by each grouped section).
  const renderChats = (list: NotebookChatSession[]) =>
    viewMode === 'grid' ? (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {list.map((main) => (
          <ChatCard
            key={main.id}
            main={main}
            sideChats={chat.sideSessionsOf(main.id)}
            newChatLabel={newChatLabel}
            allTags={allTags}
            tagColors={tagColors}
            relativeTime={relativeTime}
            onOpenMain={() => enterChat(main.id)}
            onOpenSide={(sideId) => enterChat(sideId)}
            onDelete={() => setPendingDelete(main)}
            onRename={(title) => chat.renameSession(main.id, title)}
            onSaveTags={(tags) => chat.setSessionTags(main.id, tags)}
            onTagClick={toggleTagFilter}
            onSetTagColor={setTagColor}
            activeTags={activeTags}
          />
        ))}
      </div>
    ) : (
      <ul className="flex flex-col divide-y divide-border-2 overflow-hidden rounded-xl border border-border bg-card">
        {list.map((main) => (
          <ChatRow
            key={main.id}
            main={main}
            sideCount={chat.sideSessionsOf(main.id).length}
            newChatLabel={newChatLabel}
            allTags={allTags}
            tagColors={tagColors}
            relativeTime={relativeTime}
            onOpenMain={() => enterChat(main.id)}
            onDelete={() => setPendingDelete(main)}
            onRename={(title) => chat.renameSession(main.id, title)}
            onSaveTags={(tags) => chat.setSessionTags(main.id, tags)}
            onTagClick={toggleTagFilter}
            onSetTagColor={setTagColor}
            activeTags={activeTags}
          />
        ))}
      </ul>
    )

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-6 py-8">
        {/* Gallery header + view toggle + primary action */}
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-foreground">{t('gallery.title')}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{t('gallery.subtitle')}</p>
          </div>
          <div className="flex flex-shrink-0 items-center gap-2">
            {mains.length > 0 && <ViewToggle mode={viewMode} onChange={setViewMode} />}
            <Button onClick={startNewMainChat} className="gap-2">
              <Plus className="h-4 w-4" />
              {t('gallery.startNewMainChat')}
            </Button>
          </div>
        </div>

        {/* Search + grouping + tag-group filter toolbar */}
        {mains.length > 0 && (
          <div className="mb-5 space-y-3">
            <div className="flex items-center gap-2">
              <div className="relative max-w-sm flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-3" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t('gallery.searchPlaceholder')}
                  className="pl-9"
                />
              </div>
              {allTags.length > 0 && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setGroupByTag((g) => !g)}
                  aria-pressed={groupByTag}
                  className={cn(
                    'flex-shrink-0 gap-2',
                    groupByTag && 'border-primary-soft-border bg-accent-soft text-primary'
                  )}
                >
                  <Layers className="h-4 w-4" />
                  {t('gallery.groupByTag')}
                </Button>
              )}
            </div>
            {allTags.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                {allTags.map((tag) => {
                  const colorKey = resolveTagColorKey(tag, tagColors)
                  const style = tagColorStyle(colorKey)
                  return (
                    <EditableTagChip
                      key={tag}
                      tag={tag}
                      variant="filter"
                      chipClass={style.chip}
                      solidClass={style.solid}
                      colorKey={colorKey}
                      active={activeTags.includes(tag)}
                      onToggle={() => toggleTagFilter(tag)}
                      onRename={(newName) => handleRenameTag(tag, newName)}
                      onSetColor={(key) => setTagColor(tag, key)}
                    />
                  )
                })}
                {filtersActive && (
                  <button
                    type="button"
                    onClick={clearFilters}
                    className="ml-1 inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs text-text-3 transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-soft-2"
                  >
                    <X className="h-3 w-3" />
                    {t('gallery.clearFilters')}
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {mains.length === 0 ? (
          <EmptyState
            icon={MessageSquare}
            title={t('gallery.emptyTitle')}
            description={t('gallery.emptyHelper')}
            action={
              <Button onClick={startNewMainChat} className="mt-5 gap-2">
                <Plus className="h-4 w-4" />
                {t('gallery.startNewMainChat')}
              </Button>
            }
            className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/40 px-6 py-16"
          />
        ) : filteredMains.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-card/40 px-6 py-12 text-center text-sm text-muted-foreground">
            {t('gallery.noResults')}
          </div>
        ) : groupByTag && allTags.length > 0 ? (
          <div className="space-y-8">
            {groups.map((group) => {
              const style = group.tag
                ? tagColorStyle(resolveTagColorKey(group.tag, tagColors))
                : null
              return (
                <section key={group.tag ?? '__untagged__'}>
                  <div className="mb-3 flex items-center gap-2">
                    {group.tag ? (
                      <EditableTagChip
                        tag={group.tag}
                        variant="header"
                        chipClass={style?.chip ?? ''}
                        solidClass={tagColorStyle(resolveTagColorKey(group.tag, tagColors)).solid}
                        colorKey={resolveTagColorKey(group.tag, tagColors)}
                        onRename={(newName) => handleRenameTag(group.tag as string, newName)}
                        onSetColor={(key) => setTagColor(group.tag as string, key)}
                      />
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-sm font-medium text-muted-foreground">
                        {t('gallery.untagged')}
                      </span>
                    )}
                    <span className="text-xs text-text-3">{group.chats.length}</span>
                    <div className="ml-2 h-px flex-1 bg-border-2" />
                  </div>
                  {renderChats(group.chats)}
                </section>
              )
            })}
          </div>
        ) : (
          renderChats(filteredMains)
        )}
      </div>

      <AlertDialog open={!!pendingDelete} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('gallery.deleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('gallery.deleteBody').replace(
                '{title}',
                pendingDelete?.title || newChatLabel
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {t('common.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function ViewToggle({
  mode,
  onChange,
}: {
  mode: ChatGalleryViewMode
  onChange: (mode: ChatGalleryViewMode) => void
}) {
  const { t } = useTranslation()
  const base =
    'flex h-8 w-8 items-center justify-center rounded-md transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-soft-2'
  return (
    <div className="flex items-center gap-0.5 rounded-lg border border-border bg-card p-0.5">
      <button
        type="button"
        aria-label={t('gallery.viewGrid')}
        aria-pressed={mode === 'grid'}
        onClick={() => onChange('grid')}
        className={cn(
          base,
          mode === 'grid'
            ? 'bg-accent text-foreground'
            : 'text-muted-foreground hover:text-foreground'
        )}
      >
        <LayoutGrid className="h-4 w-4" />
      </button>
      <button
        type="button"
        aria-label={t('gallery.viewList')}
        aria-pressed={mode === 'list'}
        onClick={() => onChange('list')}
        className={cn(
          base,
          mode === 'list'
            ? 'bg-accent text-foreground'
            : 'text-muted-foreground hover:text-foreground'
        )}
      >
        <ListIcon className="h-4 w-4" />
      </button>
    </div>
  )
}
