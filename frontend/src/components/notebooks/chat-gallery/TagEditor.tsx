'use client'

import { useRef, useState } from 'react'
import { Check, Pencil, Plus, Tag as TagIcon, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/hooks/use-translation'
import {
  resolveTagColorKey,
  TAG_COLOR_KEYS,
  tagColorStyle,
  type TagColorKey,
} from '@/lib/utils/tag-colors'

export type TagColorMap = Record<string, string>

// Swatch-grid color picker for a single tag. `children` is the trigger.
export function TagColorPicker({
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

// Read-only tag chips shown on a card/row; clicking one toggles it as a gallery
// filter. stopPropagation keeps the click off the parent's "open chat" handler.
export function TagChips({
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
export function EditableTagChip({
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

// Popover tag editor: add free-form tags (Enter), remove with ✕, recolor each
// tag via its swatch, or click an existing notebook tag to apply it. Persists
// the whole list on every change.
export function TagEditor({
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
