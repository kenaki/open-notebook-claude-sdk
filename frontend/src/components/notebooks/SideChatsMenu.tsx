'use client'

import { MessagesSquare } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useChatWorkspaceStore } from '@/lib/stores/chat-workspace-store'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { NotebookChatSession } from '@/lib/types/api'

interface SideChatsMenuProps {
  // All side chats of the active main (incl. hidden ones) — from
  // chat.sideSessionsOf(activeMainId).
  sideSessions: NotebookChatSession[]
  // Open (pop out) a side chat as a panel.
  onOpen: (id: string) => void
}

/**
 * The active main's "side chats (n)" control (Sidebar redesign / Chunk 4). Side
 * chats never appear in the sidebar (Decision 3/5); this dropdown is the only way
 * to reach a hidden one. Count includes hidden side chats; an open one shows a dot.
 * Renders nothing when the active main has no side chats.
 */
export function SideChatsMenu({ sideSessions, onOpen }: SideChatsMenuProps) {
  const { t } = useTranslation()
  const chats = useChatWorkspaceStore((s) => s.chats)
  const newChatLabel = t('chat.newChat')

  if (sideSessions.length === 0) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 gap-1.5 px-2 text-[11px] text-muted-foreground"
          title={t('chat.sideChats')}
        >
          <MessagesSquare className="h-3.5 w-3.5" />
          {t('chat.sideChatsCount').replace('{count}', sideSessions.length.toString())}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel>{t('chat.sideChats')}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {sideSessions.map((s) => {
          const isOpen = chats[s.id]?.open
          return (
            <DropdownMenuItem
              key={s.id}
              onSelect={() => onOpen(s.id)}
              className="flex items-center gap-2"
            >
              <span className="flex-1 truncate">{s.title || newChatLabel}</span>
              {isOpen && (
                <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-primary" aria-hidden />
              )}
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
