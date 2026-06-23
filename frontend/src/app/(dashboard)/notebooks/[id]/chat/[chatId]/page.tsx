'use client'

import { useParams } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { DeepDiveWorkspace } from '@/components/notebooks/DeepDiveWorkspace'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useNotebookWorkspace } from '@/components/notebooks/NotebookWorkspaceProvider'
import { useTranslation } from '@/lib/hooks/use-translation'

/**
 * Dual-Panel Deep Dive route (tier 3). The active Main Chat is the `chatId` path
 * segment; shared notebook state (sources, notes, the multiplexed chat hook)
 * comes from the {@link NotebookWorkspaceProvider} mounted by the notebook layout,
 * which stays alive across the Gallery ↔ Deep-Dive transition.
 */
export default function NotebookChatPage() {
  const { t } = useTranslation()
  const params = useParams()
  const chatId = params?.chatId ? decodeURIComponent(params.chatId as string) : ''
  const workspace = useNotebookWorkspace()

  if (!workspace || workspace.notebookLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (!workspace.notebook) {
    return (
      <AppShell>
        <div className="p-6">
          <h1 className="text-2xl font-bold mb-4">{t('notebooks.notFound')}</h1>
          <p className="text-muted-foreground">{t('notebooks.notFoundDesc')}</p>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <DeepDiveWorkspace activeChatId={chatId} />
    </AppShell>
  )
}
