'use client'

import { useCallback, useEffect, useState } from 'react'

/**
 * Reader typography: body text size, heading size, and line spacing.
 *
 * Unlike the last-read page, this is a reading preference rather than a
 * property of a document — it is stored once, globally, and applies to every
 * source's reader.
 *
 * `headingScale` multiplies the reader's own heading ramp (see
 * `.reader-typography` in globals.css) so headings can be tuned independently
 * of body text, rather than only scaling with it as `em` sizing would.
 */
const STORAGE_KEY = 'reader-typography'

export interface ReaderTypography {
  /** Body text size, in px. Matches Tailwind `prose-sm` (0.875rem) by default. */
  fontSize: number
  /** Multiplier on the heading ramp. 1 = the reader's default sizes. */
  headingScale: number
  /** Unitless line-height for body text. */
  lineHeight: number
}

export const READER_TYPOGRAPHY_DEFAULTS: ReaderTypography = {
  fontSize: 14,
  headingScale: 1,
  lineHeight: 1.7,
}

export const READER_TYPOGRAPHY_BOUNDS = {
  fontSize: { min: 12, max: 24, step: 1, decimals: 0 },
  headingScale: { min: 0.8, max: 1.6, step: 0.1, decimals: 1 },
  lineHeight: { min: 1.2, max: 2.2, step: 0.1, decimals: 1 },
} as const

export type ReaderTypographyKey = keyof ReaderTypography

/**
 * Clamp into range and snap to the step's precision — 0.1 steps otherwise
 * accumulate float error (1.7 + 0.1 = 1.7999999999999998) and a hand-edited or
 * older stored value can be out of range entirely.
 */
export function clampSetting(key: ReaderTypographyKey, value: number): number {
  const { min, max, decimals } = READER_TYPOGRAPHY_BOUNDS[key]
  if (!Number.isFinite(value)) return READER_TYPOGRAPHY_DEFAULTS[key]
  const clamped = Math.min(Math.max(value, min), max)
  return Number(clamped.toFixed(decimals))
}

export function readStoredTypography(): ReaderTypography {
  if (typeof window === 'undefined') return READER_TYPOGRAPHY_DEFAULTS
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return READER_TYPOGRAPHY_DEFAULTS
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return READER_TYPOGRAPHY_DEFAULTS
    const stored = parsed as Partial<Record<ReaderTypographyKey, unknown>>
    return {
      fontSize: clampSetting('fontSize', Number(stored.fontSize)),
      headingScale: clampSetting('headingScale', Number(stored.headingScale)),
      lineHeight: clampSetting('lineHeight', Number(stored.lineHeight)),
    }
  } catch {
    // Absent, unparseable, or storage disabled — read at the defaults.
    return READER_TYPOGRAPHY_DEFAULTS
  }
}

export function writeStoredTypography(typography: ReaderTypography): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(typography))
  } catch {
    // Private mode / storage disabled — the setting still applies this session.
  }
}

export function useReaderTypography() {
  // Read lazily on mount, not during render: the server has no localStorage, so
  // reading it at render time would hydrate against different markup.
  const [typography, setTypography] = useState<ReaderTypography>(READER_TYPOGRAPHY_DEFAULTS)
  useEffect(() => {
    setTypography(readStoredTypography())
  }, [])

  // State updates and the write stay outside the updater — React may invoke an
  // updater twice (StrictMode), and persistence is a side effect.
  const apply = useCallback((next: ReaderTypography) => {
    setTypography(next)
    writeStoredTypography(next)
  }, [])

  const setSetting = useCallback(
    (key: ReaderTypographyKey, value: number) => {
      const clamped = clampSetting(key, value)
      if (typography[key] === clamped) return
      apply({ ...typography, [key]: clamped })
    },
    [typography, apply]
  )

  const reset = useCallback(() => apply(READER_TYPOGRAPHY_DEFAULTS), [apply])

  return { typography, setSetting, reset }
}
