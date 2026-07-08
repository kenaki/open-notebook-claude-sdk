import { create } from 'zustand'

/**
 * Agent console (agent-console B1) — which job's console, if any, is open.
 * Ephemeral, client-only UI state (no persist): a slide-over that tails a
 * single command job's live progress. `open`/`close` are called from the job
 * tray, the pending-chat-bubble "view process" button, and the console's own
 * close/backdrop/Esc handlers (B2/B3).
 */
interface AgentConsoleState {
  openJobId: string | null
  open: (jobId: string) => void
  close: () => void
}

export const useAgentConsoleStore = create<AgentConsoleState>((set) => ({
  openJobId: null,
  open: (jobId) => set({ openJobId: jobId }),
  close: () => set({ openJobId: null }),
}))
