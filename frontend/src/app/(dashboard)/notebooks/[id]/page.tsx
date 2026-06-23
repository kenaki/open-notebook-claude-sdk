'use client'

import { AppShell } from '@/components/layout/AppShell'
import { NotebookHeader } from '../components/NotebookHeader'
import { ChatGallery } from '@/components/notebooks/ChatGallery'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useNotebookWorkspace } from '@/components/notebooks/NotebookWorkspaceProvider'
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
      <div className="flex flex-col flex-1 min-h-0">
        <div className="flex-shrink-0 px-6 py-3 border-b border-border">
          <NotebookHeader notebook={workspace.notebook} />
        </div>
        <ChatGallery />
      </div>
    </AppShell>
  )
}
