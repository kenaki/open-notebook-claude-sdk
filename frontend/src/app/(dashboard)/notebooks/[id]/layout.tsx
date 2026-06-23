'use client'

import { useParams } from 'next/navigation'
import { NotebookWorkspaceProvider } from '@/components/notebooks/NotebookWorkspaceProvider'

/**
 * Layout shared by the notebook Chat Gallery (`/notebooks/[id]`) and the
 * Dual-Panel Deep Dive (`/notebooks/[id]/chat/[chatId]`). Mounting the workspace
 * provider here keeps it alive across the Gallery ↔ Deep-Dive transition (the
 * App Router preserves a layout while navigating between its child routes), so
 * sources/notes, context selections and the chat session list don't re-fetch or
 * reset when the user enters or leaves a chat.
 */
export default function NotebookLayout({ children }: { children: React.ReactNode }) {
  const params = useParams()
  const notebookId = params?.id ? decodeURIComponent(params.id as string) : ''

  // Key by notebookId so switching notebooks (A → B) remounts the provider and
  // resets its internal state (context selections, bulk-context defaults) instead
  // of bleeding the old notebook's sources/notes into the new one's chat context.
  // Gallery ↔ Deep-Dive share the same id, so the key is stable there → no remount.
  return (
    <NotebookWorkspaceProvider key={notebookId} notebookId={notebookId}>
      {children}
    </NotebookWorkspaceProvider>
  )
}
