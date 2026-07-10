import { beforeEach, describe, expect, it } from 'vitest'
import {
  READER_TYPOGRAPHY_DEFAULTS,
  clampSetting,
  readStoredTypography,
  writeStoredTypography,
} from './use-reader-typography'

describe('clampSetting', () => {
  it('clamps into range', () => {
    expect(clampSetting('fontSize', 99)).toBe(24)
    expect(clampSetting('fontSize', 2)).toBe(12)
    expect(clampSetting('headingScale', 5)).toBe(1.6)
    expect(clampSetting('lineHeight', 0)).toBe(1.2)
  })

  it('passes an in-range value through', () => {
    expect(clampSetting('fontSize', 18)).toBe(18)
    expect(clampSetting('headingScale', 1.2)).toBe(1.2)
  })

  // Stepping by 0.1 accumulates float error; each step must land on a clean
  // value or the readout shows 1.7999999999999998 and equality checks fail.
  it('snaps 0.1 steps to one decimal', () => {
    expect(clampSetting('lineHeight', 1.7 + 0.1)).toBe(1.8)
    expect(clampSetting('headingScale', 0.8 + 0.1 + 0.1)).toBe(1)
  })

  it('falls back to the default for a non-finite value', () => {
    expect(clampSetting('fontSize', Number.NaN)).toBe(READER_TYPOGRAPHY_DEFAULTS.fontSize)
  })
})

describe('typography storage', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('round-trips settings', () => {
    const custom = { fontSize: 20, headingScale: 1.3, lineHeight: 2 }
    writeStoredTypography(custom)
    expect(readStoredTypography()).toEqual(custom)
  })

  it('returns defaults when nothing is stored', () => {
    expect(readStoredTypography()).toEqual(READER_TYPOGRAPHY_DEFAULTS)
  })

  it.each(['not json', '[]', 'null', '"str"'])('returns defaults for %j', (raw) => {
    window.localStorage.setItem('reader-typography', raw)
    expect(readStoredTypography()).toEqual(READER_TYPOGRAPHY_DEFAULTS)
  })

  // An out-of-range or partial entry (older build, hand-edited) must not reach
  // the reader as a font-size.
  it('clamps an out-of-range stored value', () => {
    window.localStorage.setItem(
      'reader-typography',
      JSON.stringify({ fontSize: 400, headingScale: -2, lineHeight: 1.5 })
    )
    expect(readStoredTypography()).toEqual({ fontSize: 24, headingScale: 0.8, lineHeight: 1.5 })
  })

  it('fills a missing field with its default', () => {
    window.localStorage.setItem('reader-typography', JSON.stringify({ fontSize: 16 }))
    expect(readStoredTypography()).toEqual({
      fontSize: 16,
      headingScale: READER_TYPOGRAPHY_DEFAULTS.headingScale,
      lineHeight: READER_TYPOGRAPHY_DEFAULTS.lineHeight,
    })
  })
})
