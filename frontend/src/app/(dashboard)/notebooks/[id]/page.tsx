'use client'

import { AppShell } from '@/components/layout/AppShell'
import { NotebookHeader } from '../components/NotebookHeader'
import { ChatGallery } from '@/components/notebooks/ChatGallery'
import { GallerySkeleton } from '@/components/notebooks/GallerySkeleton'
import { useNotebookWorkspace } from '@/components/notebooks/NotebookWorkspaceProvider'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'

// Re-exported for backward compatibility — historically these types lived here.
// They now own a dedicated module; keep the re-export so any stragglers resolve.
export type { ContextMode, ContextSelections } from '@/lib/types/notebook-context'

/**
 * Notebook landing screen — the Chat Gallery (tier 2 of the three-tier flow:
 * Notebook Selection → Chat Gallery → Dual-Panel Deep Dive). The heavy chat
 * workspace orchestration now lives in the Deep-Dive route; shared state comes
 * from {@link NotebookWorkspaceProvider} via the notebook layout.
 */
export default function NotebookGalleryPage() {
  const { t } = useTranslation()
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
      <div className="flex flex-col flex-1 min-h-0">
        <div className="flex-shrink-0 px-6 py-3 border-b border-border">
          <NotebookHeader notebook={workspace.notebook} />
        </div>
        <ChatGallery />
      </div>
    </AppShell>
  )
}
