'use client'

import { AppSidebar } from './AppSidebar'
import { SetupBanner } from './SetupBanner'
import { UtilityDrawer } from '@/components/notebooks/UtilityDrawer'

interface AppShellProps {
  children: React.ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex h-screen overflow-hidden">
      <AppSidebar />
      {/* Single utility drawer (Sources / Notes), slid out right of the rail.
          Renders only inside a notebook; collapses to zero width otherwise. */}
      <UtilityDrawer />
      <main className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <SetupBanner />
        {children}
      </main>
    </div>
  )
}
