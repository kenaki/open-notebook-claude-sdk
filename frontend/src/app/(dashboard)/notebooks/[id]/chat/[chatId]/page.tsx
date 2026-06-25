'use client'

import { useParams } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { DeepDiveWorkspace } from '@/components/notebooks/workspace'
import { GallerySkeleton } from '@/components/notebooks/GallerySkeleton'
import { useNotebookWorkspace } from '@/components/notebooks/workspace'
import { Button } from '@/components/ui/button'
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

  // Keep the app chrome mounted on cold open; swap only the content area to a
  // skeleton instead of a full-screen spinner outside the shell (no flash).
  if (!workspace || workspace.notebookLoading) {
    return (
      <AppShell>
        <GallerySkeleton />
      </AppShell>
    )
  }

  if (!workspace.notebook) {
    // Transient failure (500/network) → recoverable error card with retry.
    if (workspace.notebookFetchError) {
      return (
        <AppShell>
          <div className="p-6 max-w-lg">
            <h1 className="text-2xl font-bold mb-2">{t('notebooks.loadError')}</h1>
            <p className="text-muted-foreground mb-4">{t('notebooks.loadErrorDesc')}</p>
            <Button onClick={() => workspace.refetchNotebook()}>{t('common.retry')}</Button>
          </div>
        </AppShell>
      )
    }
    // Genuine 404 (or settled with no data) → "not found".
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
