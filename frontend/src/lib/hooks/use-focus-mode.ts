'use client'

import { useSearchParams } from 'next/navigation'

/**
 * Any window/tab opened with `?focus=1` renders in "focus mode" — chromeless
 * content-only layout (no sidebar/drawer, no JobTray/AgentConsole/CommandPalette)
 * and suppresses background-job toasts (Decisions #2 in
 * .claude/plans/cross-interface-study/coordinator.md). Used by pop-out windows
 * (reader / workspace) so a second OS window doesn't double the app chrome or
 * double-toast job completions — the main window stays the single notifier.
 */
export function useFocusMode(): boolean {
  const searchParams = useSearchParams()
  return searchParams?.get('focus') === '1'
}
