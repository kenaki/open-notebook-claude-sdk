'use client'

import { ChatDock } from '@/components/notebooks/chat'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Card, CardContent } from '@/components/ui/card'
import { AlertCircle } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { useNotebookChat } from '@/lib/hooks/useNotebookChat'

interface ChatColumnContextStats {
  sourcesInsights: number
  sourcesFull: number
  notesCount: number
  tokenCount?: number
  charCount?: number
}

interface ChatColumnProps {
  notebookId: string
  // The multiplexed chat hook is lifted to the notebook page so popped-out chat
  // panels (track siblings of the dock) can share one instance (Plan C / Chunk 8).
  chat: ReturnType<typeof useNotebookChat>
  contextStats: ChatColumnContextStats
  loading: boolean
  // True when the notebook's sources/notes failed to load entirely.
  error?: boolean
  // Allow popping chats out of the dock (desktop only — see ChatDock).
  enablePopOut?: boolean
}

export function ChatColumn({ notebookId, chat, contextStats, loading, error = false, enablePopOut }: ChatColumnProps) {
  const { t } = useTranslation()

  // Show loading state while sources/notes are being fetched
  if (loading) {
    return (
      <Card className="h-full flex flex-col">
        <CardContent className="flex-1 flex items-center justify-center">
          <LoadingSpinner size="lg" />
          <span className="sr-only">{t('common.loading')}</span>
        </CardContent>
      </Card>
    )
  }

  // Show error state if data fetch failed (unlikely but good to handle)
  if (error) {
    return (
      <Card className="h-full flex flex-col">
        <CardContent className="flex-1 flex items-center justify-center">
          <div className="text-center text-muted-foreground">
            <AlertCircle className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p className="text-sm">{t('chat.unableToLoadChat')}</p>
            <p className="text-xs mt-2">{t('common.refreshPage') || 'Please try refreshing the page'}</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <ChatDock
      notebookId={notebookId}
      chat={chat}
      contextStats={contextStats}
      enablePopOut={enablePopOut}
    />
  )
}
