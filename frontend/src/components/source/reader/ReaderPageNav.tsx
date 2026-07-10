'use client'

import { useEffect, useState } from 'react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { clampPage } from '@/lib/utils/page-index'

/**
 * Jump-to-page control for the reader toolbar. The field mirrors the page the
 * user is currently scrolled to, and typing a page + Enter (or blurring) jumps
 * there — the caller resolves page -> block seq via the parse header's
 * `page_index` and scrolls, loading the containing span if needed.
 *
 * Out-of-range input is clamped rather than rejected, so "999" in an 84-page
 * document goes to the last page instead of doing nothing.
 */
export function ReaderPageNav({
  currentPage,
  pageCount,
  onJumpToPage,
}: {
  currentPage: number | null
  pageCount: number
  onJumpToPage: (page: number) => void
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState(false)

  // While the user isn't typing, the field tracks the scroll position.
  useEffect(() => {
    if (!editing) setDraft(currentPage != null ? String(currentPage) : '')
  }, [currentPage, editing])

  if (pageCount < 1) return null

  const commit = () => {
    setEditing(false)
    const page = clampPage(Number(draft), pageCount)
    if (page == null) {
      setDraft(currentPage != null ? String(currentPage) : '')
      return
    }
    setDraft(String(page))
    onJumpToPage(page)
  }

  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <label htmlFor="reader-page-input" className="sr-only">
        {t('sources.reader.pageNavLabel')}
      </label>
      <input
        id="reader-page-input"
        type="text"
        inputMode="numeric"
        value={draft}
        onChange={(e) => {
          setEditing(true)
          setDraft(e.target.value.replace(/[^0-9]/g, ''))
        }}
        onFocus={(e) => e.currentTarget.select()}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            e.currentTarget.blur()
          } else if (e.key === 'Escape') {
            e.preventDefault()
            setEditing(false)
            setDraft(currentPage != null ? String(currentPage) : '')
            e.currentTarget.blur()
          }
        }}
        aria-label={t('sources.reader.pageNavLabel')}
        className="h-7 w-12 rounded border border-border bg-background px-1.5 text-center text-xs tabular-nums outline-none focus:ring-1 focus:ring-ring"
      />
      <span className="tabular-nums">
        {t('sources.reader.pageOfCount').replace('{count}', String(pageCount))}
      </span>
    </div>
  )
}
