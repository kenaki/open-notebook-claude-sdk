import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

import { RecallReferences } from './RecallReferences'
import type { RecallRef } from '@/lib/types/api'

// `useTranslation` is globally mocked to the identity function (see
// src/test/setup.ts) so `t('chat.recallRelated')` renders as the literal key.

const exchangeRef: RecallRef = {
  kind: 'exchange',
  title: 'Discussing gradient descent',
  session_id: 'chat_session:abc123',
  scope: 'notebook',
  source_id: null,
  notebook_id: 'notebook:xyz',
  message_id: 'msg:1',
  annotation_id: null,
  page: null,
  quote: 'What is the learning rate?',
  similarity: 0.82,
}

const annotationRef: RecallRef = {
  kind: 'annotation',
  title: 'Chapter 3 — Backpropagation',
  session_id: null,
  scope: null,
  source_id: 'source:def456',
  notebook_id: null,
  message_id: null,
  annotation_id: 'source_annotation:ghi789',
  page: 42,
  quote: 'the chain rule applied layer by layer',
  similarity: 0.91,
}

describe('RecallReferences', () => {
  it('renders nothing when refs is empty', () => {
    const { container } = render(<RecallReferences refs={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders one pill per ref, with a page chip for the annotation ref', () => {
    render(<RecallReferences refs={[exchangeRef, annotationRef]} />)

    expect(screen.getByText('chat.recallRelated')).toBeInTheDocument()
    expect(screen.getByText('Discussing gradient descent')).toBeInTheDocument()
    expect(screen.getByText('Chapter 3 — Backpropagation')).toBeInTheDocument()
    // Only the annotation ref carries a page.
    expect(screen.getByText('chat.recallRefPage')).toBeInTheDocument()
  })

  it('shows the quote snippet and kind label in the popover, and dispatches onOpenRef', () => {
    const onOpenRef = vi.fn()
    render(<RecallReferences refs={[annotationRef]} onOpenRef={onOpenRef} />)

    fireEvent.click(screen.getByText('Chapter 3 — Backpropagation'))

    expect(screen.getByText('the chain rule applied layer by layer')).toBeInTheDocument()
    expect(screen.getByText('chat.recallKindAnnotation')).toBeInTheDocument()

    fireEvent.click(screen.getByText('chat.recallJumpToHighlight'))
    expect(onOpenRef).toHaveBeenCalledWith(annotationRef)
  })

  it('falls back to the kind label as the pill title when title is absent', () => {
    render(<RecallReferences refs={[{ ...exchangeRef, title: null }]} />)
    expect(screen.getByText('chat.recallKindExchange')).toBeInTheDocument()
  })
})
