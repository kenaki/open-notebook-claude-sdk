'use client'

import { useRouter } from 'next/navigation'
import { useMemo, useRef, useState } from 'react'
import { formatDistanceToNow } from 'date-fns'
import { getDateLocale } from '@/lib/utils/date-locale'
import {
  MessageSquare,
  Plus,
  CornerDownRight,
  LayoutGrid,
  List as ListIcon,
  Trash2,
  Search,
  Tag as TagIcon,
  X,
  Layers,
  Check,
  Pencil,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
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
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useNotebookWorkspaceStrict } from '@/components/notebooks/NotebookWorkspaceProvider'
import {
  useChatGalleryViewStore,
  type ChatGalleryViewMode,
} from '@/lib/stores/chat-gallery-view-store'
import {
  resolveTagColorKey,
  tagColorStyle,
  TAG_COLOR_KEYS,
  type TagColorKey,
} from '@/lib/utils/tag-colors'
import type { NotebookChatSession } from '@/lib/types/api'

type TagColorMap = Record<string, string>

/**
 * Notebook Chat Gallery (UI refactor — tier 2 of the three-tier flow). The
 * landing screen after a notebook is selected: past Main Chats laid out either
 * as a roomy card grid or a compact list (toggle persisted per-browser). A
 * search box filters by title or tag; chats can be grouped with free-form tags
 * (persisted on the session) that double as one-click filter chips, carry a
 * per-notebook color, and — via "Group by tag" — section the gallery into
 * tagged groups. Each card surfaces its nested Side Chats so the hierarchy reads
 * at a glance. Cards/rows enter the Dual-Panel Deep Dive
 * (`/notebooks/[id]/chat/[chatId]`); "Start New Main Chat" spins one up and
 * jumps straight in. A per-chat delete (with confirmation) removes a Main Chat.
 */
export function ChatGallery() {
  const { t, language } = useTranslation()
  const router = useRouter()
  const { notebookId, chat, tagColors, setTagColor, renameTag } = useNotebookWorkspaceStrict()
  const dfLocale = getDateLocale(language)
  const viewMode = useChatGalleryViewStore((s) => s.viewMode)
  const setViewMode = useChatGalleryViewStore((s) => s.setViewMode)
  // Main chat queued for deletion (drives the confirmation dialog).
  const [pendingDelete, setPendingDelete] = useState<NotebookChatSession | null>(null)
  // Free-text search (title + tags) and the active tag-group filter (AND).
  const [query, setQuery] = useState('')
  const [activeTags, setActiveTags] = useState<string[]>([])
  const [groupByTag, setGroupByTag] = useState(false)

  const newChatLabel = t('chat.newChat')
  const mains = chat.mainSessions

  // Every tag in use across this notebook's main chats — drives the filter row,
  // the grouped sections, and the editor's suggestions. Sorted, de-duped.
  const allTags = useMemo(() => {
    const seen = new Map<string, string>()
    for (const m of mains) {
      for (const tag of m.tags ?? []) {
        const key = tag.toLowerCase()
        if (!seen.has(key)) seen.set(key, tag)
      }
    }
    return [...seen.values()].sort((a, b) => a.localeCompare(b))
  }, [mains])

  // Apply search + active-tag filters. A chat matches the query if its title or
  // any tag contains it; it matches the tag filter if it carries every active tag.
  const filteredMains = useMemo(() => {
    const q = query.trim().toLowerCase()
    const active = activeTags.map((tag) => tag.toLowerCase())
    return mains.filter((m) => {
      const tags = m.tags ?? []
      if (active.length > 0) {
        const lower = tags.map((tag) => tag.toLowerCase())
        if (!active.every((tag) => lower.includes(tag))) return false
      }
      if (q) {
        const inTitle = (m.title || newChatLabel).toLowerCase().includes(q)
        const inTags = tags.some((tag) => tag.toLowerCase().includes(q))
        if (!inTitle && !inTags) return false
      }
      return true
    })
  }, [mains, query, activeTags, newChatLabel])

  // Sectioned view: one group per tag (chats with multiple tags appear in each),
  // plus a trailing "Untagged" group. Built from the already-filtered chats.
  const groups = useMemo(() => {
    const out: { tag: string | null; chats: NotebookChatSession[] }[] = []
    for (const tag of allTags) {
      const lower = tag.toLowerCase()
      const chats = filteredMains.filter((m) =>
        (m.tags ?? []).some((tg) => tg.toLowerCase() === lower)
      )
      if (chats.length > 0) out.push({ tag, chats })
    }
    const untagged = filteredMains.filter((m) => (m.tags ?? []).length === 0)
    if (untagged.length > 0) out.push({ tag: null, chats: untagged })
    return out
  }, [allTags, filteredMains])

  const relativeTime = (d: string) =>
    formatDistanceToNow(new Date(d), { addSuffix: true, locale: dfLocale })

  const enterChat = (chatId: string) => {
    router.push(`/notebooks/${notebookId}/chat/${chatId}`)
  }

  // Optimistic spawn (Track A / A1): a temp card lands in the list and we jump
  // straight into the Deep-Dive at the temp id, then reconcile the URL to the
  // real session once it lands (or fall back to the gallery if creation failed).
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

  const toggleTagFilter = (tag: string) => {
    setActiveTags((prev) =>
      prev.includes(tag) ? prev.filter((tg) => tg !== tag) : [...prev, tag]
    )
  }

  // Rename a tag notebook-wide, then keep any active filter pointing at the new
  // name (de-duped) so the view doesn't empty out after the rename.
  const handleRenameTag = (oldTag: string, newName: string) => {
    const trimmed = newName.trim()
    renameTag(oldTag, trimmed)
    if (!trimmed) return
    setActiveTags((prev) => {
      const mapped = prev.map((tg) =>
        tg.toLowerCase() === oldTag.toLowerCase() ? trimmed : tg
      )
      return [...new Set(mapped)]
    })
  }

  const filtersActive = query.trim().length > 0 || activeTags.length > 0
  const clearFilters = () => {
    setQuery('')
    setActiveTags([])
  }

  // Render a set of chats in the current view mode (reused by the flat view and
  // by each grouped section).
  const renderChats = (list: NotebookChatSession[]) =>
    viewMode === 'grid' ? (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {list.map((main) => (
          <MainChatCard
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
          <MainChatRow
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
          <EmptyState onStart={startNewMainChat} />
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

// Inline-rename chat title for a gallery card/row. A hover/focus pencil turns the
// heading into a text field; Enter or blur commits, Escape cancels. Every handler
// stops propagation so editing never triggers the parent's navigate-on-click.
function EditableChatTitle({
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

function MainChatCard({
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

function MainChatRow({
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

// Read-only tag chips shown on a card/row; clicking one toggles it as a gallery
// filter. Colored by the tag's resolved color. stopPropagation keeps the click
// off the parent's "open chat" handler.
function TagChips({
  tags,
  tagColors,
  activeTags,
  onTagClick,
  className,
}: {
  tags: string[]
  tagColors: TagColorMap
  activeTags: string[]
  onTagClick: (tag: string) => void
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap gap-1', className)}>
      {tags.map((tag) => {
        const style = tagColorStyle(resolveTagColorKey(tag, tagColors))
        return (
          <button
            key={tag}
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onTagClick(tag)
            }}
            className={cn(
              'inline-flex max-w-full items-center gap-1 truncate rounded-full px-2 py-0.5 text-[11px] transition-shadow',
              style.chip,
              activeTags.includes(tag) ? 'ring-2 ring-current/50' : 'opacity-90 hover:opacity-100'
            )}
          >
            <TagIcon className="h-2.5 w-2.5 flex-shrink-0" />
            <span className="truncate">{tag}</span>
          </button>
        )
      })}
    </div>
  )
}

// A tag pill with inline rename. Pencil (hover/focus) or double-click turns the
// label into a text field; Enter / blur commits the rename notebook-wide,
// Escape cancels. The "filter" variant single-clicks to toggle the gallery
// filter; the "header" variant leads with a color swatch (opens the picker) and
// single-clicks the label to rename.
function EditableTagChip({
  tag,
  variant,
  chipClass,
  solidClass,
  colorKey,
  active,
  onToggle,
  onRename,
  onSetColor,
}: {
  tag: string
  variant: 'filter' | 'header'
  chipClass: string
  solidClass: string
  colorKey: TagColorKey
  active?: boolean
  onToggle?: () => void
  onRename: (newName: string) => void
  onSetColor: (key: TagColorKey) => void
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(tag)
  // Guard against the Enter-then-blur double commit (both fire onRename).
  const committed = useRef(false)
  const isHeader = variant === 'header'

  const startEdit = () => {
    committed.current = false
    setDraft(tag)
    setEditing(true)
  }
  const commit = () => {
    if (committed.current) return
    committed.current = true
    setEditing(false)
    const trimmed = draft.trim()
    if (trimmed && trimmed !== tag) onRename(trimmed)
  }
  const cancel = () => {
    committed.current = true
    setEditing(false)
    setDraft(tag)
  }

  const sizeClass = isHeader ? 'px-2.5 py-1 text-sm font-medium' : 'px-2.5 py-1 text-xs'

  if (editing) {
    return (
      <span className={cn('inline-flex items-center gap-1 rounded-full', chipClass, sizeClass)}>
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onFocus={(e) => e.target.select()}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              commit()
            } else if (e.key === 'Escape') {
              e.preventDefault()
              cancel()
            }
          }}
          onBlur={commit}
          aria-label={t('gallery.renameTag')}
          className="w-28 bg-transparent text-current outline-none placeholder:text-current/50"
        />
      </span>
    )
  }

  return (
    <span
      className={cn(
        'group/tag inline-flex items-center gap-1 rounded-full transition-shadow',
        chipClass,
        sizeClass,
        active ? 'ring-2 ring-current/50' : !isHeader && 'opacity-80 hover:opacity-100'
      )}
    >
      {isHeader ? (
        <TagColorPicker tag={tag} colorKey={colorKey} onPick={onSetColor}>
          <button
            type="button"
            title={t('gallery.tagColor')}
            aria-label={t('gallery.tagColor')}
            onClick={(e) => e.stopPropagation()}
            className={cn(
              'h-3 w-3 flex-shrink-0 rounded-full ring-1 ring-inset ring-black/10 transition-transform hover:scale-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-soft-2',
              solidClass
            )}
          />
        </TagColorPicker>
      ) : (
        <TagIcon className="h-3 w-3 flex-shrink-0" />
      )}

      <button
        type="button"
        onClick={onToggle ?? startEdit}
        onDoubleClick={(e) => {
          e.stopPropagation()
          startEdit()
        }}
        aria-pressed={onToggle ? !!active : undefined}
        aria-label={onToggle ? tag : t('gallery.renameTag')}
        className="max-w-[12rem] truncate outline-none focus-visible:underline"
      >
        {tag}
      </button>

      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          startEdit()
        }}
        aria-label={t('gallery.renameTag')}
        title={t('gallery.renameTag')}
        className="flex-shrink-0 opacity-0 transition-opacity focus-visible:opacity-100 group-hover/tag:opacity-100"
      >
        <Pencil className="h-3 w-3" />
      </button>
    </span>
  )
}

// Swatch-grid color picker for a single tag. `children` is the trigger.
function TagColorPicker({
  colorKey,
  onPick,
  children,
}: {
  tag: string
  colorKey: TagColorKey
  onPick: (key: TagColorKey) => void
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent align="start" className="w-auto p-2" onClick={(e) => e.stopPropagation()}>
        <div className="grid grid-cols-5 gap-1.5">
          {TAG_COLOR_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              aria-label={key}
              onClick={() => {
                onPick(key)
                setOpen(false)
              }}
              className={cn(
                'flex h-6 w-6 items-center justify-center rounded-full transition-transform hover:scale-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-soft-2',
                tagColorStyle(key).solid
              )}
            >
              {key === colorKey && <Check className="h-3.5 w-3.5 text-white" />}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}

// Popover tag editor: add free-form tags (Enter), remove with ✕, recolor each
// tag via its swatch, or click an existing notebook tag to apply it. Persists
// the whole list on every change.
function TagEditor({
  tags,
  allTags,
  tagColors,
  onSave,
  onSetTagColor,
}: {
  tags: string[]
  allTags: string[]
  tagColors: TagColorMap
  onSave: (tags: string[]) => void
  onSetTagColor: (tag: string, colorKey: string) => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')

  const addTag = (raw: string) => {
    const value = raw.trim()
    if (!value) return
    if (tags.some((tag) => tag.toLowerCase() === value.toLowerCase())) {
      setDraft('')
      return
    }
    onSave([...tags, value])
    setDraft('')
  }

  const removeTag = (tag: string) => {
    onSave(tags.filter((tg) => tg !== tag))
  }

  // Notebook tags not yet on this chat — quick-add suggestions.
  const suggestions = allTags.filter(
    (tag) => !tags.some((tg) => tg.toLowerCase() === tag.toLowerCase())
  )

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t('gallery.editTags')}
          title={t('gallery.editTags')}
          onClick={(e) => e.stopPropagation()}
          className={cn(
            'flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md text-text-3 transition-all hover:bg-accent hover:text-foreground focus:outline-none focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent-soft-2',
            tags.length > 0 ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
          )}
        >
          <TagIcon className="h-4 w-4" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-64 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {tags.map((tag) => {
              const colorKey = resolveTagColorKey(tag, tagColors)
              const style = tagColorStyle(colorKey)
              return (
                <span
                  key={tag}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-full py-0.5 pl-1 pr-1.5 text-[11px]',
                    style.chip
                  )}
                >
                  <TagColorPicker
                    tag={tag}
                    colorKey={colorKey}
                    onPick={(key) => onSetTagColor(tag, key)}
                  >
                    <button
                      type="button"
                      aria-label={t('gallery.tagColor')}
                      title={t('gallery.tagColor')}
                      className={cn(
                        'h-3 w-3 flex-shrink-0 rounded-full ring-1 ring-inset ring-black/10',
                        style.solid
                      )}
                    />
                  </TagColorPicker>
                  <span className="truncate">{tag}</span>
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
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              addTag(draft)
            }
          }}
          placeholder={t('gallery.tagInputPlaceholder')}
          className="h-8 text-sm"
        />
        {suggestions.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {suggestions.map((tag) => (
              <button
                key={tag}
                type="button"
                onClick={() => addTag(tag)}
                className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <Plus className="h-2.5 w-2.5" />
                {tag}
              </button>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}

// Hover-revealed delete affordance shared by card + row. stopPropagation keeps
// the click from bubbling to the parent's "open chat" handler.
function DeleteButton({ label, onDelete }: { label: string; onDelete: () => void }) {
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

function EmptyState({ onStart }: { onStart: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/40 px-6 py-16 text-center">
      <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-accent-soft text-primary">
        <MessageSquare className="h-6 w-6" />
      </span>
      <h3 className="text-sm font-semibold text-foreground">{t('gallery.emptyTitle')}</h3>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">{t('gallery.emptyHelper')}</p>
      <Button onClick={onStart} className="mt-5 gap-2">
        <Plus className="h-4 w-4" />
        {t('gallery.startNewMainChat')}
      </Button>
    </div>
  )
}
