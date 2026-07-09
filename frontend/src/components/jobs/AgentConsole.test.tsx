import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'

import { AgentConsole, coalesceEvents } from './AgentConsole'
import { useAgentConsoleStore } from '@/lib/stores/agent-console-store'
import { useJobsStore } from '@/lib/stores/jobs-store'
import type { CommandJobDetail, JobEvent } from '@/lib/types/api'

// The console's data query (B1) is TanStack-Query-backed; mock it directly so
// this render test doesn't need a QueryClientProvider — we only care that the
// console renders whatever shape `useAgentConsole` hands it.
const mockUseAgentConsole = vi.fn()
vi.mock('@/lib/hooks/use-agent-console', () => ({
  useAgentConsole: (jobId: string | null) => mockUseAgentConsole(jobId),
}))

const JOB_ID = 'command:abc123'

const detailFixture: CommandJobDetail = {
  job_id: JOB_ID,
  name: 'chat',
  status: 'running',
  args: { context: 'the built context blob', message: 'What does this paper argue?' },
  progress: {
    phase: 'Searching sources',
    events: [
      { t: '2026-01-01T00:00:00Z', type: 'phase', label: 'Extracting text' },
      { t: '2026-01-01T00:00:01Z', type: 'tool_call', tool_name: 'search_sources', tool_input: { query: 'thesis' } },
      { t: '2026-01-01T00:00:02Z', type: 'tool_result', tool_name: 'search_sources', preview: 'result preview', is_error: false },
      { t: '2026-01-01T00:00:03Z', type: 'thinking', text: 'First thought.' },
      { t: '2026-01-01T00:00:04Z', type: 'thinking', text: 'Second thought continues.' },
      { t: '2026-01-01T00:00:05Z', type: 'context', chars: 1234, preview: 'context preview text' },
    ],
  },
}

function openConsoleFor(detail: CommandJobDetail) {
  mockUseAgentConsole.mockReturnValue({ data: detail, isLoading: false })
  act(() => {
    useJobsStore.setState({
      jobs: [
        {
          jobId: JOB_ID,
          kind: 'notebook_chat',
          label: '',
          status: 'running',
          startedAt: new Date().toISOString(),
          sessionId: 's1',
          notebookId: 'n1',
        },
      ],
    })
    useAgentConsoleStore.setState({ openJobId: JOB_ID })
  })
}

beforeEach(() => {
  mockUseAgentConsole.mockReset()
  mockUseAgentConsole.mockReturnValue({ data: undefined, isLoading: false })
  act(() => {
    useJobsStore.setState({ jobs: [] })
    useAgentConsoleStore.setState({ openJobId: null })
  })
})

describe('coalesceEvents', () => {
  it('merges consecutive thinking events into a single row', () => {
    const events = detailFixture.progress?.events as JobEvent[]
    const rows = coalesceEvents(events)

    const thinkingRows = rows.filter((r) => r.kind === 'thinking')
    expect(thinkingRows).toHaveLength(1)
    expect(thinkingRows[0]).toMatchObject({ text: 'First thought. Second thought continues.' })

    // Non-thinking rows pass through untouched.
    expect(rows.filter((r) => r.kind === 'phase')).toHaveLength(1)
    expect(rows.filter((r) => r.kind === 'tool_call')).toHaveLength(1)
    expect(rows.filter((r) => r.kind === 'tool_result')).toHaveLength(1)
    expect(rows.filter((r) => r.kind === 'context')).toHaveLength(1)
  })

  it('keeps non-adjacent thinking events as separate rows', () => {
    const events: JobEvent[] = [
      { t: '1', type: 'thinking', text: 'alpha' },
      { t: '2', type: 'phase', label: 'Searching sources' },
      { t: '3', type: 'thinking', text: 'beta' },
    ]
    const rows = coalesceEvents(events)
    const thinkingRows = rows.filter((r) => r.kind === 'thinking')
    expect(thinkingRows).toHaveLength(2)
  })
})

describe('AgentConsole', () => {
  it('renders nothing when no job is open', () => {
    render(<AgentConsole />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders a job\'s event feed with thinking coalesced into one block', () => {
    openConsoleFor(detailFixture)
    render(<AgentConsole />)

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Extracting text')).toBeInTheDocument()
    expect(screen.getByText('First thought. Second thought continues.')).toBeInTheDocument()
    // Exactly one "Thinking" label — the two thinking events coalesced.
    expect(screen.getAllByText('console.thinking')).toHaveLength(1)
  })

  it('switches to the Context tab and shows the context payload', () => {
    openConsoleFor(detailFixture)
    render(<AgentConsole />)

    // Radix Tabs switches on `mousedown`, not `click` — see TabsTrigger's
    // `onMouseDown` handler (@radix-ui/react-tabs).
    fireEvent.mouseDown(screen.getByText('console.context'))

    expect(screen.getByText('context preview text')).toBeInTheDocument()
    expect(screen.getByText('the built context blob')).toBeInTheDocument()
    expect(screen.getByText('What does this paper argue?')).toBeInTheDocument()
  })

  it('shows the empty state when a job has no events yet', () => {
    openConsoleFor({ ...detailFixture, status: 'new', progress: { events: [] } })
    render(<AgentConsole />)

    expect(screen.getByText('console.empty')).toBeInTheDocument()
  })
})
