'use client'

import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'
import { formatDistanceToNow } from 'date-fns'
import { getDateLocale } from '@/lib/utils/date-locale'
import {
  MessageSquare,
  Plus,
  CornerDownRight,
  Loader2,
  LayoutGrid,
  List as ListIcon,
  Trash2,
  Search,
  Tag as TagIcon,
  X,
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
import type { NotebookChatSession } from '@/lib/types/api'

/**
 * Notebook Chat Gallery (UI refactor — tier 2 of the three-tier flow). The
 * landing screen after a notebook is selected: past Main Chats laid out either
 * as a roomy card grid or a compact list (toggle persisted per-browser). A
 * search box filters by title or tag, and chats can be grouped with free-form
 * tags (persisted on the session) that double as one-click filter chips. Each
 * card surfaces its nested Side Chats so the hierarchy reads at a glance.
 * Cards/rows enter the Dual-Panel Deep Dive (`/notebooks/[id]/chat/[chatId]`);
 * "Start New Main Chat" spins one up and jumps straight in. A per-chat delete
 * (with confirmation) removes a Main Chat.
 */
export function ChatGallery() {
  const { t, language } = useTranslation()
  const router = useRouter()
  const { notebookId, chat } = useNotebookWorkspaceStrict()
  const dfLocale = getDateLocale(language)
  const [creating, setCreating] = useState(false)
  const viewMode = useChatGalleryViewStore((s) => s.viewMode)
  const setViewMode = useChatGalleryViewStore((s) => s.setViewMode)
  // Main chat queued for deletion (drives the confirmation dialog).
  const [pendingDelete, setPendingDelete] = useState<NotebookChatSession | null>(null)
  // Free-text search (title + tags) and the active tag-group filter (AND).
  const [query, setQuery] = useState('')
  const [activeTags, setActiveTags] = useState<string[]>([])

  const newChatLabel = t('chat.newChat')
  const mains = chat.mainSessions

  // Every tag in use across this notebook's main chats — drives the filter row
  // and the editor's suggestions. Sorted, de-duped (case-insensitive).
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

  const relativeTime = (d: string) =>
    formatDistanceToNow(new Date(d), { addSuffix: true, locale: dfLocale })

  const enterChat = (chatId: string) => {
    router.push(`/notebooks/${notebookId}/chat/${chatId}`)
  }

  const startNewMainChat = async () => {
    if (creating) return
    setCreating(true)
    try {
      const session = await chat.createSession(newChatLabel)
      if (session) enterChat(session.id)
    } finally {
      setCreating(false)
    }
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

  const filtersActive = query.trim().length > 0 || activeTags.length > 0
  const clearFilters = () => {
    setQuery('')
    setActiveTags([])
  }

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
            <Button onClick={startNewMainChat} disabled={creating} className="gap-2">
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              {t('gallery.startNewMainChat')}
            </Button>
          </div>
        </div>

        {/* Search + tag-group filter toolbar */}
        {mains.length > 0 && (
          <div className="mb-5 space-y-3">
            <div className="relative max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-3" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('gallery.searchPlaceholder')}
                className="pl-9"
              />
            </div>
            {allTags.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                {allTags.map((tag) => {
                  const active = activeTags.includes(tag)
                  return (
                    <button
                      key={tag}
                      type="button"
                      onClick={() => toggleTagFilter(tag)}
                      aria-pressed={active}
                      className={cn(
                        'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-soft-2',
                        active
                          ? 'border-primary-soft-border bg-accent-soft text-primary'
                          : 'border-border text-muted-foreground hover:bg-accent hover:text-foreground'
                      )}
                    >
                      <TagIcon className="h-3 w-3" />
                      {tag}
                    </button>
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
          <EmptyState onStart={startNewMainChat} creating={creating} />
        ) : filteredMains.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-card/40 px-6 py-12 text-center text-sm text-muted-foreground">
            {t('gallery.noResults')}
          </div>
        ) : viewMode === 'grid' ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {filteredMains.map((main) => (
              <MainChatCard
                key={main.id}
                main={main}
                sideChats={chat.sideSessionsOf(main.id)}
                newChatLabel={newChatLabel}
                allTags={allTags}
                relativeTime={relativeTime}
                onOpenMain={() => enterChat(main.id)}
                onOpenSide={(sideId) => enterChat(sideId)}
                onDelete={() => setPendingDelete(main)}
                onSaveTags={(tags) => chat.setSessionTags(main.id, tags)}
                onTagClick={toggleTagFilter}
                activeTags={activeTags}
              />
            ))}
          </div>
        ) : (
          <ul className="flex flex-col divide-y divide-border-2 overflow-hidden rounded-xl border border-border bg-card">
            {filteredMains.map((main) => (
              <MainChatRow
                key={main.id}
                main={main}
                sideCount={chat.sideSessionsOf(main.id).length}
                newChatLabel={newChatLabel}
                allTags={allTags}
                relativeTime={relativeTime}
                onOpenMain={() => enterChat(main.id)}
                onDelete={() => setPendingDelete(main)}
                onSaveTags={(tags) => chat.setSessionTags(main.id, tags)}
                onTagClick={toggleTagFilter}
                activeTags={activeTags}
              />
            ))}
          </ul>
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

function MainChatCard({
  main,
  sideChats,
  newChatLabel,
  allTags,
  relativeTime,
  onOpenMain,
  onOpenSide,
  onDelete,
  onSaveTags,
  onTagClick,
  activeTags,
}: {
  main: NotebookChatSession
  sideChats: NotebookChatSession[]
  newChatLabel: string
  allTags: string[]
  relativeTime: (date: string) => string
  onOpenMain: () => void
  onOpenSide: (sideId: string) => void
  onDelete: () => void
  onSaveTags: (tags: string[]) => void
  onTagClick: (tag: string) => void
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
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-foreground">
            {main.title || newChatLabel}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{relativeTime(main.updated)}</p>
        </div>
        <TagEditor tags={tags} allTags={allTags} onSave={onSaveTags} />
        <DeleteButton label={t('gallery.deleteChat')} onDelete={onDelete} />
      </div>

      {tags.length > 0 && (
        <TagChips tags={tags} activeTags={activeTags} onTagClick={onTagClick} className="mt-3" />
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
  relativeTime,
  onOpenMain,
  onDelete,
  onSaveTags,
  onTagClick,
  activeTags,
}: {
  main: NotebookChatSession
  sideCount: number
  newChatLabel: string
  allTags: string[]
  relativeTime: (date: string) => string
  onOpenMain: () => void
  onDelete: () => void
  onSaveTags: (tags: string[]) => void
  onTagClick: (tag: string) => void
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
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-sm font-medium text-foreground">
          {main.title || newChatLabel}
        </h3>
        <p className="mt-0.5 text-xs text-muted-foreground">{relativeTime(main.updated)}</p>
      </div>
      {tags.length > 0 && (
        <TagChips
          tags={tags}
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
      <TagEditor tags={tags} allTags={allTags} onSave={onSaveTags} />
      <DeleteButton label={t('gallery.deleteChat')} onDelete={onDelete} />
    </li>
  )
}

// Read-only tag chips shown on a card/row; clicking one toggles it as a gallery
// filter. stopPropagation keeps the click off the parent's "open chat" handler.
function TagChips({
  tags,
  activeTags,
  onTagClick,
  className,
}: {
  tags: string[]
  activeTags: string[]
  onTagClick: (tag: string) => void
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap gap-1', className)}>
      {tags.map((tag) => (
        <button
          key={tag}
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onTagClick(tag)
          }}
          className={cn(
            'inline-flex max-w-full items-center gap-1 truncate rounded-full px-2 py-0.5 text-[11px] transition-colors',
            activeTags.includes(tag)
              ? 'bg-accent-soft text-primary'
              : 'bg-accent text-muted-foreground hover:text-foreground'
          )}
        >
          <TagIcon className="h-2.5 w-2.5 flex-shrink-0" />
          <span className="truncate">{tag}</span>
        </button>
      ))}
    </div>
  )
}

// Popover tag editor: add free-form tags (Enter), remove with ✕, or click an
// existing notebook tag to apply it. Persists the whole list on every change.
function TagEditor({
  tags,
  allTags,
  onSave,
}: {
  tags: string[]
  allTags: string[]
  onSave: (tags: string[]) => void
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
            {tags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] text-primary"
              >
                {tag}
                <button
                  type="button"
                  aria-label={`${t('common.delete')} ${tag}`}
                  onClick={() => removeTag(tag)}
                  className="rounded-full hover:text-foreground"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </span>
            ))}
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

function EmptyState({ onStart, creating }: { onStart: () => void; creating: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/40 px-6 py-16 text-center">
      <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-accent-soft text-primary">
        <MessageSquare className="h-6 w-6" />
      </span>
      <h3 className="text-sm font-semibold text-foreground">{t('gallery.emptyTitle')}</h3>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">{t('gallery.emptyHelper')}</p>
      <Button onClick={onStart} disabled={creating} className="mt-5 gap-2">
        {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        {t('gallery.startNewMainChat')}
      </Button>
    </div>
  )
}
