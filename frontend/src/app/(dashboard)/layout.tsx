'use client'

import { useAuth } from '@/lib/hooks/use-auth'
import { useVersionCheck } from '@/lib/hooks/use-version-check'
import { useFocusMode } from '@/lib/hooks/use-focus-mode'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { ModalProvider } from '@/components/providers/ModalProvider'
import { CreateDialogsProvider } from '@/lib/hooks/use-create-dialogs'
import { CommandPalette } from '@/components/common/CommandPalette'
import { JobsRuntime } from '@/components/jobs/JobsRuntime'
import { JobTray } from '@/components/jobs/JobTray'
import { AgentConsole } from '@/components/jobs/AgentConsole'

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const [hasCheckedAuth, setHasCheckedAuth] = useState(false)
  const focusMode = useFocusMode()

  // Check for version updates once per session
  useVersionCheck()

  useEffect(() => {
    // Mark that we've completed the initial auth check
    if (!isLoading) {
      setHasCheckedAuth(true)

      // Redirect to login if not authenticated
      if (!isAuthenticated) {
        // Store the current path to redirect back after login
        const currentPath = window.location.pathname + window.location.search
        sessionStorage.setItem('redirectAfterLogin', currentPath)
        router.push('/login')
      }
    }
  }, [isAuthenticated, isLoading, router])

  // Show loading spinner during initial auth check or while loading
  if (isLoading || !hasCheckedAuth) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  // Don't render anything if not authenticated (during redirect)
  if (!isAuthenticated) {
    return null
  }

  // Focus-mode windows (`?focus=1`) — pop-out reader/chat windows — render
  // content only: no CommandPalette/JobTray/AgentConsole (the main window is
  // the single surface for those), and the poller stays quiet (no toasts) so
  // job completions don't double-notify across windows (Decisions #2).
  if (focusMode) {
    return (
      <ErrorBoundary>
        <CreateDialogsProvider>
          {children}
          <ModalProvider />
          <JobsRuntime quiet />
        </CreateDialogsProvider>
      </ErrorBoundary>
    )
  }

  return (
    <ErrorBoundary>
      <CreateDialogsProvider>
        {children}
        <ModalProvider />
        <CommandPalette />
        <JobsRuntime />
        <JobTray />
        <AgentConsole />
      </CreateDialogsProvider>
    </ErrorBoundary>
  )
}
