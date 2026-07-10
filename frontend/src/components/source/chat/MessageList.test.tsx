import type { ReactElement } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi } from 'vitest'

import { MessageList } from './MessageList'
import { useAnnotationJumpStore } from '@/lib/stores/annotation-jump-store'
import type { RecallRef, SourceChatMessage } from '@/lib/types/api'

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

// study-memory C2: wiring-level coverage that MessageList actually dispatches
// a recall-pill click through `navigateToRecallRef` with real props/store —
// the branch table itself is exhaustively covered at the pure-function level
// in `lib/utils/recall-navigation.test.ts` (all four branches + edge cases).
describe('MessageList recall-ref dispatch', () => {
  const exchangeSameSourceRef: RecallRef = {
    kind: 'exchange',
    title: 'Discussing gradient descent',
    session_id: 'chat_session:same-src',
    scope: 'source',
    source_id: 'source:abc',
    notebook_id: null,
    message_id: null,
    annotation_id: null,
    page: null,
    quote: 'What is the learning rate?',
    similarity: 0.82,
  }

  const annotationSameSourceRef: RecallRef = {
    kind: 'annotation',
    title: 'Chapter 3 — Backpropagation',
    session_id: null,
    scope: null,
    source_id: 'source:abc',
    notebook_id: null,
    message_id: null,
    annotation_id: 'source_annotation:ghi',
    page: 42,
    quote: 'the chain rule applied layer by layer',
    similarity: 0.91,
  }

  it('same-source-chat exchange pill calls onSwitchSession in place', () => {
    const onSwitchSession = vi.fn()
    const messages: SourceChatMessage[] = [
      { ...baseMessage, recall_refs: [exchangeSameSourceRef] },
    ]

    renderWithQueryClient(
      <MessageList
        messages={messages}
        isStreaming={false}
        isDock={false}
        sourceId="source:abc"
        onReferenceClick={noop}
        onSuggestion={noop}
        onSwitchSession={onSwitchSession}
      />
    )

    fireEvent.click(screen.getByText('Discussing gradient descent'))
    fireEvent.click(screen.getByText('chat.recallOpenSession'))

    expect(onSwitchSession).toHaveBeenCalledWith('chat_session:same-src')
  })

  it('same-source annotation pill requests a jump via the annotation-jump store', () => {
    const handler = vi.fn()
    useAnnotationJumpStore.getState().register('source:abc', handler)

    const messages: SourceChatMessage[] = [
      { ...baseMessage, recall_refs: [annotationSameSourceRef] },
    ]

    renderWithQueryClient(
      <MessageList
        messages={messages}
        isStreaming={false}
        isDock={false}
        sourceId="source:abc"
        onReferenceClick={noop}
        onSuggestion={noop}
      />
    )

    fireEvent.click(screen.getByText('Chapter 3 — Backpropagation'))
    fireEvent.click(screen.getByText('chat.recallJumpToHighlight'))

    expect(handler).toHaveBeenCalledWith('source_annotation:ghi')
    useAnnotationJumpStore.getState().unregister('source:abc')
  })
})
