'use client'

import { useJobsPoller } from '@/lib/hooks/use-jobs-poller'

/**
 * Invisible app-level component that drives the background-jobs poller.
 *
 * Mount once inside the authenticated dashboard layout. It calls `useJobsPoller`
 * (which polls /commands/jobs while work is in flight and reconciles results into
 * the Zustand jobs store) and renders nothing.
 */
export function JobsRuntime() {
  useJobsPoller()
  return null
}
