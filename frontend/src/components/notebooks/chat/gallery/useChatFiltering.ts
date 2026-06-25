import { useMemo, useState } from 'react'
import type { NotebookChatSession } from '@/lib/types/api'

export function useChatFiltering(
  mains: NotebookChatSession[],
  newChatLabel: string,
  renameTag: (oldTag: string, newName: string) => void
) {
  const [query, setQuery] = useState('')
  const [activeTags, setActiveTags] = useState<string[]>([])
  const [groupByTag, setGroupByTag] = useState(false)

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

  const toggleTagFilter = (tag: string) => {
    setActiveTags((prev) =>
      prev.includes(tag) ? prev.filter((tg) => tg !== tag) : [...prev, tag]
    )
  }

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

  return {
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
  }
}
