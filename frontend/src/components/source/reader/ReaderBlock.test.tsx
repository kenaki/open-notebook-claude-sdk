import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Annotation, Block } from '@/lib/types/api'
import { ReaderBlockItem } from './ReaderBlock'

/**
 * pdf-block-ingestion Track D6/D7 — the `code` block renderer. Guards the two
 * paths that matter: syntax highlighting on an un-annotated block, and the
 * fall-back to plain `<mark>`-segmented text once an annotation covers it.
 */

function codeBlock(text: string, seq = 1): Block {
  return { seq, type: 'code', page: 1, text }
}

function anchoredAnnotation(seq: number, start: number, end: number): Annotation {
  return {
    id: 'annotation:a1',
    color: '#fde68a',
    anchor_state: 'anchored',
    block_seq: seq,
    block_end_seq: seq,
    anchor_start: start,
    anchor_end: end,
  } as Annotation
}

const PYTHON = 'import os\n\nclass Foo:\n    def __init__(self, n):\n        self.n = n\n'

describe('ReaderBlockItem — code', () => {
  it('syntax-highlights an un-annotated code block', () => {
    const { container } = render(
      <ReaderBlockItem item={{ kind: 'block', block: codeBlock(PYTHON) }} />
    )
    // hljs tokenized the source rather than emitting one flat text node.
    expect(container.querySelectorAll('code.hljs .hljs-keyword').length).toBeGreaterThan(0)
    // The verbatim source survives for the copy button / text selection.
    expect(container.querySelector('code')?.textContent).toBe(PYTHON)
  })

  it('keeps the block reachable by seq for selection anchoring', () => {
    const { container } = render(
      <ReaderBlockItem item={{ kind: 'block', block: codeBlock(PYTHON, 42) }} />
    )
    expect(container.querySelector('[data-seq="42"]')).not.toBeNull()
  })

  it('renders plain text with no colors when the source is prose, not code', () => {
    const prose = 'The quick brown fox jumps over the lazy dog.'
    const { container } = render(
      <ReaderBlockItem item={{ kind: 'block', block: codeBlock(prose) }} />
    )
    expect(container.querySelector('code.hljs')).toBeNull()
    expect(container.querySelector('code')?.textContent).toBe(prose)
  })

  it('falls back to <mark> segmentation when an annotation covers the block', () => {
    const hl = {
      annotations: [anchoredAnnotation(1, 0, 6)],
      onAnnotationClick: () => {},
      onAtomicSelect: () => {},
    }
    const { container } = render(
      <ReaderBlockItem item={{ kind: 'block', block: codeBlock(PYTHON) }} hl={hl} />
    )
    // Syntax colors yield to the user's highlight...
    expect(container.querySelector('code.hljs')).toBeNull()
    // ...which paints exactly the annotated slice.
    expect(screen.getByText('import')).toBeInstanceOf(HTMLElement)
    expect(container.querySelector('mark')?.textContent).toBe('import')
    expect(container.querySelector('code')?.textContent).toBe(PYTHON)
  })
})
