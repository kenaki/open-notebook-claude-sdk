import { describe, it, expect } from 'vitest'
import {
  buildPageSpans,
  pageForSeq,
  firstSeqFromPage,
  clampPage,
  nextChunkWindow,
} from './page-index'

// `page_index[i]` describes page i+1 as [first_seq, last_seq]; a page with no
// blocks stores the inverted sentinel [0, -1].
const PAGES = [
  [1, 5], // page 1
  [6, 6], // page 2
  [0, -1], // page 3 — empty (e.g. a full-bleed image with no extracted blocks)
  [7, 12], // page 4
]

describe('buildPageSpans', () => {
  it('drops empty pages and keeps 1-based page numbers', () => {
    expect(buildPageSpans(PAGES)).toEqual([
      { page: 1, lo: 1, hi: 5 },
      { page: 2, lo: 6, hi: 6 },
      { page: 4, lo: 7, hi: 12 },
    ])
  })

  it('returns [] for a source parsed before page_index was served', () => {
    expect(buildPageSpans(undefined)).toEqual([])
    expect(buildPageSpans([])).toEqual([])
  })
})

describe('pageForSeq', () => {
  const spans = buildPageSpans(PAGES)

  it('finds the page holding a seq, including range boundaries', () => {
    expect(pageForSeq(spans, 1)).toBe(1)
    expect(pageForSeq(spans, 5)).toBe(1)
    expect(pageForSeq(spans, 6)).toBe(2)
    expect(pageForSeq(spans, 7)).toBe(4)
    expect(pageForSeq(spans, 12)).toBe(4)
  })

  it('never resolves to an empty page', () => {
    expect(pageForSeq(spans, 6)).not.toBe(3)
    expect(pageForSeq(spans, 7)).not.toBe(3)
  })

  it('returns null for a seq outside every range', () => {
    expect(pageForSeq(spans, 0)).toBeNull()
    expect(pageForSeq(spans, 13)).toBeNull()
    expect(pageForSeq(spans, NaN)).toBeNull()
    expect(pageForSeq([], 1)).toBeNull()
  })
})

describe('firstSeqFromPage', () => {
  const spans = buildPageSpans(PAGES)

  it('returns the first seq on the requested page', () => {
    expect(firstSeqFromPage(spans, 1)).toBe(1)
    expect(firstSeqFromPage(spans, 2)).toBe(6)
    expect(firstSeqFromPage(spans, 4)).toBe(7)
  })

  it('falls through an empty page to the next page with blocks', () => {
    expect(firstSeqFromPage(spans, 3)).toBe(7)
  })

  it('returns null when no page at or after the request has blocks', () => {
    expect(firstSeqFromPage(spans, 5)).toBeNull()
    expect(firstSeqFromPage([], 1)).toBeNull()
  })
})

describe('clampPage', () => {
  it('clamps into [1, pageCount] and truncates', () => {
    expect(clampPage(0, 84)).toBe(1)
    expect(clampPage(999, 84)).toBe(84)
    expect(clampPage(12, 84)).toBe(12)
    expect(clampPage(12.7, 84)).toBe(12)
  })

  it('returns null for unusable input', () => {
    expect(clampPage(NaN, 84)).toBeNull()
    expect(clampPage(5, 0)).toBeNull()
  })
})

describe('nextChunkWindow', () => {
  it('is a no-op when the chunk is already loaded', () => {
    const prev = [0, 1]
    expect(nextChunkWindow(prev, 1)).toBe(prev)
  })

  it('grows the window for an adjacent chunk', () => {
    expect(nextChunkWindow([0], 1).sort()).toEqual([0, 1])
    expect(nextChunkWindow([5, 6], 4).sort()).toEqual([4, 5, 6])
    expect(nextChunkWindow([5, 6], 7).sort()).toEqual([5, 6, 7])
  })

  // The bug this exists for: jumping to page 1000 from page 1 used to append,
  // leaving {0, 99}. Both chunks render into one seq-ordered list, so page 10
  // sat directly above page 991 and scrolling up from the target reported
  // page 10. A far jump must relocate the window instead.
  it('relocates the window on a far jump', () => {
    expect(nextChunkWindow([0], 99)).toEqual([99])
    expect(nextChunkWindow([0, 1], 50)).toEqual([50])
  })

  it('relocates rather than leaving a one-chunk hole', () => {
    expect(nextChunkWindow([0], 2)).toEqual([2])
  })

  it('handles an empty window', () => {
    expect(nextChunkWindow([], 7)).toEqual([7])
  })

  it('always yields a contiguous window', () => {
    let window = [0]
    for (const chunk of [1, 2, 99, 98, 50, 51]) {
      window = nextChunkWindow(window, chunk)
      const sorted = [...window].sort((a, b) => a - b)
      const gaps = sorted.filter((c, i) => i > 0 && c !== sorted[i - 1] + 1)
      expect(gaps).toEqual([])
    }
  })
})
