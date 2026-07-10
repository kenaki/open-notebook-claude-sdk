'use client'

import { useParams } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { DeepDiveWorkspace } from '@/components/notebooks/workspace'
import { GallerySkeleton } from '@/components/notebooks/GallerySkeleton'
import { useNotebookWorkspace } from '@/components/notebooks/workspace'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useFocusMode } from '@/lib/hooks/use-focus-mode'

/**
 * Wraps content in the AppShell chrome, or — in focus mode — a bare
 * full-viewport flex container mirroring what AppShell's <main> provides
 * (DeepDiveWorkspace expects a flex/min-h-0 ancestor to size correctly). A
 * plain function (not a component) so it doesn't create a new component type
 * on every render — that would remount `children` each time.
 */
function withChrome(focusMode: boolean, children: React.ReactNode) {
  return focusMode ? (
    <div className="flex h-screen flex-col overflow-hidden">{children}</div>
  ) : (
    <AppShell>{children}</AppShell>
  )
}

/**
 * Dual-Panel Deep Dive route (tier 3). The active Main Chat is the `chatId` path
 * segment; shared notebook state (sources, notes, the multiplexed chat hook)
 * comes from the {@link NotebookWorkspaceProvider} mounted by the notebook layout,
 * which stays alive across the Gallery ↔ Deep-Dive transition.
 *
 * `?focus=1` (pop-out windows, cross-interface-study Track C) renders full
 * viewport WITHOUT the AppShell chrome — no sidebar, no top bar — mirroring the
 * chromeless `/sources/[id]` template. The `NotebookWorkspaceProvider` lives in
 * the notebook layout above this page and is unaffected by the gate.
 */
export default function NotebookChatPage() {
  const { t } = useTranslation()
  const params = useParams()
  const chatId = params?.chatId ? decodeURIComponent(params.chatId as string) : ''
  const workspace = useNotebookWorkspace()
  const focusMode = useFocusMode()

  // Keep the app chrome mounted on cold open; swap only the content area to a
  // skeleton instead of a full-screen spinner outside the shell (no flash).
  if (!workspace || workspace.notebookLoading) {
    return withChrome(focusMode, <GallerySkeleton />)
  }

  if (!workspace.notebook) {
    // Transient failure (500/network) → recoverable error card with retry.
    if (workspace.notebookFetchError) {
      return withChrome(
        focusMode,
        <div className="p-6 max-w-lg">
          <h1 className="text-2xl font-bold mb-2">{t('notebooks.loadError')}</h1>
          <p className="text-muted-foreground mb-4">{t('notebooks.loadErrorDesc')}</p>
          <Button onClick={() => workspace.refetchNotebook()}>{t('common.retry')}</Button>
        </div>
      )
    }
    // Genuine 404 (or settled with no data) → "not found".
    return withChrome(
      focusMode,
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4">{t('notebooks.notFound')}</h1>
        <p className="text-muted-foreground">{t('notebooks.notFoundDesc')}</p>
      </div>
    )
  }

  return withChrome(focusMode, <DeepDiveWorkspace activeChatId={chatId} />)
}
