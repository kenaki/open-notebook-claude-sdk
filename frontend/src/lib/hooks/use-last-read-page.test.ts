import { beforeEach, describe, expect, it } from 'vitest'
import { readStoredPage, writeStoredPage } from './use-last-read-page'

describe('last-read-page storage', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('round-trips a page', () => {
    writeStoredPage('source:abc', 57)
    expect(readStoredPage('source:abc')).toBe(57)
  })

  it('scopes the page per source', () => {
    writeStoredPage('source:abc', 57)
    expect(readStoredPage('source:xyz')).toBeNull()
  })

  it('returns null when nothing is stored', () => {
    expect(readStoredPage('source:abc')).toBeNull()
  })

  // A page is 1-based; anything else is a corrupt entry from an older build or
  // a hand-edited value, and must not be handed to a viewer as a jump target.
  it.each(['0', '-3', '1.5', 'abc', ''])('rejects the invalid entry %j', (raw) => {
    window.localStorage.setItem('source-last-page-source:abc', raw)
    expect(readStoredPage('source:abc')).toBeNull()
  })
})
