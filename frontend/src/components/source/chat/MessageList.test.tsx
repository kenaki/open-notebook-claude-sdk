import type { ReactElement } from 'react'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi } from 'vitest'

import { MessageList } from './MessageList'
import type { SourceChatMessage } from '@/lib/types/api'

// Keep this render test focused on the thinking-disclosure seam (agent-console
// B3): jobs-store/agent-console-store are plain zustand (no provider needed),
// `useTranslation` is globally mocked to the identity function (see
// src/test/setup.ts) so `t('chat.thinking')` renders as the literal key —
// but MessageActions (rendered on every AI turn) calls `useQueryClient()`, so
// a QueryClientProvider is required even though this test never fires a query.

const baseMessage: SourceChatMessage = {
  id: 'msg-1',
  type: 'ai',
  content: 'The answer is 42.',
  timestamp: new Date().toISOString(),
}

const noop = vi.fn()

// jsdom doesn't implement scrollIntoView; useChatScrollAnchor calls it on
// mount for every message-list render (see ContextPreview.test.tsx precedent).
Element.prototype.scrollIntoView = () => {}

function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient()
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('MessageList thinking disclosure', () => {
  it('renders the collapsible thinking section when message.thinking is present', () => {
    const messages: SourceChatMessage[] = [
      { ...baseMessage, thinking: 'Reasoning through the steps…' },
    ]

    renderWithQueryClient(
      <MessageList
        messages={messages}
        isStreaming={false}
        isDock={false}
        onReferenceClick={noop}
        onSuggestion={noop}
      />
    )

    expect(screen.getByText('chat.thinking')).toBeInTheDocument()
  })

  it('omits the thinking section when message.thinking is absent', () => {
    const messages: SourceChatMessage[] = [{ ...baseMessage }]

    renderWithQueryClient(
      <MessageList
        messages={messages}
        isStreaming={false}
        isDock={false}
        onReferenceClick={noop}
        onSuggestion={noop}
      />
    )

    expect(screen.queryByText('chat.thinking')).not.toBeInTheDocument()
  })
})
