import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, beforeAll } from 'vitest'
import { ContextPreviewPopover } from './ContextPreview'
import type { BuildContextResponse } from '@/lib/types/api'

// Radix Popover positions its content via floating-ui, which needs these browser
// APIs that jsdom doesn't implement. Shim them so the portal can mount on open.
beforeAll(() => {
  // @ts-ignore - minimal ResizeObserver stand-in for jsdom
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.scrollIntoView = () => {}
})

// t() is mocked to return the key verbatim (src/test/setup.ts), so translated
// strings assert as their keys while literal, non-translated text (titles,
// chapter lines) asserts as-is.
const fullSource: BuildContextResponse['context'] = {
  sources: [
    {
      id: 'source:1',
      title: 'Hands on Machine Learning',
      insights: [],
      abstract: '',
      outline: [
        {
          id: 'sec:1',
          title: 'The Machine Learning Landscape',
          level: 1,
          order: 1,
          page_start: 1,
          page_end: 30,
          summary: 'Intro to ML',
          children: [],
        },
      ],
    },
  ],
  notes: [{ id: 'note:1', title: 'My note', content: 'Note body text' }],
}

function open() {
  // Hover the meter trigger — content only portals into the DOM once open.
  fireEvent.mouseEnter(screen.getByRole('button'))
}

describe('ContextPreviewPopover', () => {
  it('lists each source with its outline and a note on hover', async () => {
    render(
      <ContextPreviewPopover
        contextData={fullSource}
        tokenCount={31199}
        charCount={84165}
        sourceCount={1}
        notesCount={1}
      >
        <span>meter</span>
      </ContextPreviewPopover>,
    )
    open()

    // Source title + a chaptered "Full" body (literal, not translated).
    expect(await screen.findByText('Hands on Machine Learning')).toBeInTheDocument()
    expect(
      screen.getByText('Ch 1: The Machine Learning Landscape (pp. 1–30) — Intro to ML'),
    ).toBeInTheDocument()
    expect(screen.getByText('chat.contextPreviewModeFull')).toBeInTheDocument()

    // Note title + body.
    expect(screen.getByText('My note')).toBeInTheDocument()
    expect(screen.getByText('Note body text')).toBeInTheDocument()
  })

  it('shows the empty state when nothing is in context', async () => {
    render(
      <ContextPreviewPopover
        contextData={{ sources: [], notes: [] }}
        tokenCount={0}
        charCount={0}
        sourceCount={0}
        notesCount={0}
      >
        <span>meter</span>
      </ContextPreviewPopover>,
    )
    open()
    expect(await screen.findByText('chat.contextPreviewEmpty')).toBeInTheDocument()
  })

  it('shows a building state while the payload lags the meter', async () => {
    render(
      <ContextPreviewPopover
        contextData={null}
        tokenCount={0}
        charCount={0}
        sourceCount={1}
        notesCount={0}
      >
        <span>meter</span>
      </ContextPreviewPopover>,
    )
    open()
    expect(await screen.findByText('chat.contextPreviewBuilding')).toBeInTheDocument()
  })
})
