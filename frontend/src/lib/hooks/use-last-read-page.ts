'use client'

import { useCallback, useEffect, useMemo, useRef } from 'react'

/**
 * The last page the user read in a source, shared by the Reader and PDF tabs.
 *
 * Both tabs report the page they're scrolled to while they're active, and both
 * jump to this value when the user switches into them — so the two views stay
 * on the same page, and a reload returns to it.
 *
 * The value lives in localStorage, matching the sibling per-source tab
 * preference in SourceDetailContent. This hook is the seam for moving it to
 * SurrealDB: reimplement the two storage helpers against an endpoint and make
 * `storedPage` come from a query. No caller changes.
 */
const STORAGE_PREFIX = 'source-last-page-'

/** Coalesce a burst of scroll-driven page reports into one write. */
const WRITE_DEBOUNCE_MS = 500

/** The stored 1-based page for a source, or null when absent/corrupt. */
export function readStoredPage(sourceId: string): number | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + sourceId)
    if (raw === null) return null
    const page = Number(raw)
    return Number.isInteger(page) && page > 0 ? page : null
  } catch {
    return null
  }
}

export function writeStoredPage(sourceId: string, page: number): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + sourceId, String(page))
  } catch {
    // Private mode / storage disabled — in-session tab sync still works.
  }
}

export function useLastReadPage(sourceId: string) {
  // Read once per source, before either viewer has reported a page. The
  // viewers restore from this, so it must not observe their own reports.
  const storedPage = useMemo(() => readStoredPage(sourceId), [sourceId])

  // The live page, read synchronously when the user switches tabs. A ref, not
  // state: the viewers must not re-render on every page scrolled past — a
  // PDFViewer re-render re-runs pdf.js layout (see its memo note).
  const lastPageRef = useRef<number | null>(storedPage)
  const writtenRef = useRef<number | null>(storedPage)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    lastPageRef.current = storedPage
    writtenRef.current = storedPage
  }, [storedPage])

  const flush = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    const page = lastPageRef.current
    if (page != null && page !== writtenRef.current) {
      writtenRef.current = page
      writeStoredPage(sourceId, page)
    }
  }, [sourceId])

  const recordPage = useCallback(
    (page: number) => {
      if (!Number.isInteger(page) || page < 1) return
      if (lastPageRef.current === page) return
      lastPageRef.current = page
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(flush, WRITE_DEBOUNCE_MS)
    },
    [flush]
  )

  // Persist a debounced page still in flight when the detail view unmounts, or
  // when the source changes (the cleanup closes over the outgoing sourceId).
  useEffect(() => flush, [flush])

  return { storedPage, lastPageRef, recordPage }
}
