'use client'

import { useJobsPoller } from '@/lib/hooks/use-jobs-poller'

interface JobsRuntimeProps {
  // Focus-mode windows (`?focus=1`) keep the poller running so their data stays
  // fresh, but must not surface completion/failure toasts — the main window is
  // the single notifier (Decisions #2, cross-interface-study).
  quiet?: boolean
}

/**
 * Invisible app-level component that drives the background-jobs poller.
 *
 * Mount once inside the authenticated dashboard layout. It calls `useJobsPoller`
 * (which polls /commands/jobs while work is in flight and reconciles results into
 * the Zustand jobs store) and renders nothing.
 */
export function JobsRuntime({ quiet = false }: JobsRuntimeProps = {}) {
  useJobsPoller({ quiet })
  return null
}
