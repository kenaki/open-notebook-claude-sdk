import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ChatColumn } from './ChatColumn'
import { useNotebookChat } from '@/lib/hooks/useNotebookChat'

// ChatColumn is now presentational: the multiplexed chat hook is created by the
// notebook page and passed in (Plan C / Chunk 8). The dock is stubbed.
vi.mock('@/components/notebooks/chat', () => ({
  ChatDock: () => <div data-testid="chat-panel" />
}))

// Minimal stand-in for the lifted useNotebookChat return value.
function createChatMock() {
  return {
    sessions: [],
    currentSessionId: null,
    getMessages: () => [],
    getIsSending: () => false,
  } as unknown as ReturnType<typeof useNotebookChat>
}

const baseStats = {
  sourcesInsights: 0,
  sourcesFull: 0,
  notesCount: 0,
  tokenCount: 0,
  charCount: 0,
}

describe('ChatColumn', () => {
  const baseProps = {
    notebookId: 'test-notebook',
    chat: createChatMock(),
    contextStats: baseStats,
  }

  it('shows loading spinner when fetching data', () => {
    render(<ChatColumn {...baseProps} loading={true} />)
    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument()
  })

  it('renders chat panel when data is loaded', () => {
    render(<ChatColumn {...baseProps} loading={false} />)
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument()
  })
})
