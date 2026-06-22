'use client'

import { useMemo, useState } from 'react'
import { Plus, Search, Pencil, Check, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { DeleteChatButton } from '@/components/notebooks/DeleteChatButton'
import { useChatWorkspaceStore } from '@/lib/stores/chat-workspace-store'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { NotebookChatSession } from '@/lib/types/api'
import type { useNotebookChat } from '@/lib/hooks/useNotebookChat'

interface ChatSidebarProps {
  // The single multiplexed chat hook (lifted to the page).
  chat: ReturnType<typeof useNotebookChat>
  // Open a main chat in the dock (created by the parent so the create→refetch
  // race is handled once).
  onOpen: (id: string) => void
  // Spawn a new main chat and open it.
  onNew: () => void
}

/**
 * The chat library rail (Sidebar redesign / Chunk 2). Replaces the dock tab
 * strip: a searchable, recency-ordered list of MAIN chats (side chats never
 * appear here — Decision 3). Clicking a row opens it in the dock; the active
 * main is highlighted. Each row offers inline rename; the trash (delete) control
 * lands in Chunk 3.
 */
export function ChatSidebar({ chat, onOpen, onNew }: ChatSidebarProps) {
  const { t } = useTranslation()
  const activeChatId = useChatWorkspaceStore((s) => s.activeChatId)

  const [query, setQuery] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')

  const newChatLabel = t('chat.newChat')

  const mains = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return chat.mainSessions
    return chat.mainSessions.filter((s) => (s.title || newChatLabel).toLowerCase().includes(q))
  }, [chat.mainSessions, query, newChatLabel])

  const startRename = (session: NotebookChatSession) => {
    setEditingId(session.id)
    setEditValue(session.title || '')
  }
  const commitRename = () => {
    if (editingId) {
      const next = editValue.trim()
      if (next) chat.renameSession(editingId, next)
    }
    setEditingId(null)
  }

  return (
    <div className="flex flex-col h-full min-h-0 w-56 flex-shrink-0 border-r border-border bg-card/40">
      {/* Header: title + new chat */}
      <div className="flex-shrink-0 flex items-center justify-between gap-2 px-3 py-2.5 border-b border-border">
        <span className="text-[13px] font-semibold text-foreground">{t('chat.sidebarTitle')}</span>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 rounded-full"
          title={newChatLabel}
          aria-label={newChatLabel}
          onClick={onNew}
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      {/* Search */}
      <div className="flex-shrink-0 px-2.5 py-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('chat.searchChats')}
            className="h-8 pl-8 text-xs"
          />
        </div>
      </div>

      {/* List */}
      <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
        {mains.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-muted-foreground">{t('chat.noChats')}</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {mains.map((session) => {
              const isActive = session.id === activeChatId
              const isEditing = session.id === editingId
              return (
                <li key={session.id}>
                  {isEditing ? (
                    <div className="flex items-center gap-1 px-1.5 py-1">
                      <Input
                        autoFocus
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') commitRename()
                          if (e.key === 'Escape') setEditingId(null)
                        }}
                        className="h-7 text-xs"
                      />
                      <button
                        type="button"
                        title={t('common.save')}
                        className="p-1 rounded hover:bg-accent text-muted-foreground"
                        onClick={commitRename}
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title={t('common.cancel')}
                        className="p-1 rounded hover:bg-accent text-muted-foreground"
                        onClick={() => setEditingId(null)}
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ) : (
                    <div
                      className={`group flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs cursor-pointer transition-colors ${
                        isActive
                          ? 'bg-accent-soft text-foreground'
                          : 'text-muted-foreground hover:bg-accent'
                      }`}
                      onClick={() => onOpen(session.id)}
                      onDoubleClick={() => startRename(session)}
                    >
                      <span className="flex-1 truncate">{session.title || newChatLabel}</span>
                      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
                        <button
                          type="button"
                          title={t('chat.renameChat')}
                          className="p-0.5 rounded text-muted-foreground hover:bg-background"
                          onClick={(e) => {
                            e.stopPropagation()
                            startRename(session)
                          }}
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                        <DeleteChatButton onDelete={() => chat.deleteSession(session.id)} />
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
