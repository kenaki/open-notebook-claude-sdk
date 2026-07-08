'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useParseStatus, SOURCE_BLOCK_KEYS } from '@/lib/hooks/use-source-blocks'
import { sourcesApi } from '@/lib/api/sources'
import type { Block } from '@/lib/types/api'
import {
  buildReaderRenderItems,
  readerItemKey,
  readerItemPage,
  ReaderBlockItem,
} from './ReaderBlock'
import { ReaderOutline } from './ReaderOutline'

/**
 * pdf-block-ingestion Track D6 — the markdown reader tab: headings, KaTeX
 * equations, figure crops, and tables rendered from the block substrate
 * (db-design §2.3 "reader view", Decision #12/#14). Beside the PDF/Content
 * tabs in SourceDetailContent; only mounted once `useParseStatus` is ready.
 *
 * Progressive loading: pages are fetched in ~10-page spans (the C3 endpoint's
 * own cap) via `useQueries` sharing `useBlockSpan`'s query key shape, so a
 * span loaded here and one fetched elsewhere (e.g. a future prefetch) dedupe
 * in the TanStack cache. Two scroll sentinels (top/bottom) load the
 * neighboring span as the reader nears either edge — no virtualization lib;
 * a parsed generation's blocks are light and immutable, so once a span is
 * fetched it never re-fetches.
 */

const SPAN_SIZE = 10 // mirrors the backend's _MAX_SPAN_PAGES clamp

interface ChunkRange {
  index: number
  start: number
  end: number
}

export function ReaderView({ sourceId }: { sourceId: string }) {
  const { t } = useTranslation()
  const parseStatus = useParseStatus(sourceId)
  const gen = parseStatus.data?.gen
  const pageCount = parseStatus.data?.page_count ?? 0
  const sectionIndex = useMemo(
    () => parseStatus.data?.section_index ?? [],
    [parseStatus.data?.section_index]
  )
  const totalChunks = Math.max(1, Math.ceil((pageCount || SPAN_SIZE) / SPAN_SIZE))

  // Which ~10-page chunks (by index) are currently loaded. Resets to the
  // first chunk whenever the generation changes (a re-parse invalidates
  // page/seq numbering from a prior gen).
  const [loadedChunks, setLoadedChunks] = useState<number[]>([0])
  useEffect(() => {
    setLoadedChunks([0])
  }, [gen])

  const ranges: ChunkRange[] = useMemo(() => {
    return [...loadedChunks]
      .sort((a, b) => a - b)
      .map((index) => ({
        index,
        start: index * SPAN_SIZE + 1,
        end: Math.min((index + 1) * SPAN_SIZE, pageCount || (index + 1) * SPAN_SIZE),
      }))
  }, [loadedChunks, pageCount])

  const spanQueries = useQueries({
    queries: ranges.map((range) => ({
      queryKey: SOURCE_BLOCK_KEYS.blockSpan(sourceId, gen ?? -1, range.start, range.end),
      queryFn: () => sourcesApi.getBlockSpan(sourceId, range.start, range.end),
      enabled: !!sourceId && gen != null,
      staleTime: Infinity,
      retry: false,
      meta: { silent: true },
    })),
  })

  const blocks: Block[] = useMemo(() => {
    const bySeq = new Map<number, Block>()
    for (const query of spanQueries) {
      for (const block of query.data?.blocks ?? []) {
        bySeq.set(block.seq, block)
      }
    }
    return Array.from(bySeq.values()).sort((a, b) => a.seq - b.seq)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- spanQueries is a fresh array every render; dataUpdatedAt is the real (stable) dependency signal
  }, [spanQueries.map((q) => q.dataUpdatedAt).join(',')])

  const renderItems = useMemo(() => buildReaderRenderItems(blocks), [blocks])

  const containerRef = useRef<HTMLDivElement>(null)
  const topSentinelRef = useRef<HTMLDivElement>(null)
  const bottomSentinelRef = useRef<HTMLDivElement>(null)
  const [pendingScrollSeq, setPendingScrollSeq] = useState<number | null>(null)

  // Top/bottom scroll sentinels grow the loaded chunk window.
  useEffect(() => {
    const root = containerRef.current
    const topEl = topSentinelRef.current
    const bottomEl = bottomSentinelRef.current
    if (!root) return
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          if (entry.target === topEl) {
            setLoadedChunks((prev) => {
              const min = Math.min(...prev)
              if (min <= 0 || prev.includes(min - 1)) return prev
              return [...prev, min - 1]
            })
          } else if (entry.target === bottomEl) {
            setLoadedChunks((prev) => {
              const max = Math.max(...prev)
              if (max >= totalChunks - 1 || prev.includes(max + 1)) return prev
              return [...prev, max + 1]
            })
          }
        }
      },
      { root, rootMargin: '600px 0px', threshold: 0 }
    )
    if (topEl) observer.observe(topEl)
    if (bottomEl) observer.observe(bottomEl)
    return () => observer.disconnect()
  }, [totalChunks, gen])

  // Outline jump: scroll if the target is already rendered; otherwise resolve
  // its page via a point-get, load that chunk, and scroll once it lands.
  const handleJump = useCallback(
    async (seq: number) => {
      const existing = containerRef.current?.querySelector(`[data-seq="${seq}"]`)
      if (existing) {
        existing.scrollIntoView({ behavior: 'smooth', block: 'start' })
        return
      }
      try {
        const block = await sourcesApi.getBlock(sourceId, seq)
        if (typeof block.page === 'number') {
          const chunkIndex = Math.floor((block.page - 1) / SPAN_SIZE)
          setLoadedChunks((prev) => (prev.includes(chunkIndex) ? prev : [...prev, chunkIndex]))
        }
      } catch {
        // Nothing resolvable — no-op.
      }
      setPendingScrollSeq(seq)
    },
    [sourceId]
  )

  useEffect(() => {
    if (pendingScrollSeq == null) return
    const el = containerRef.current?.querySelector(`[data-seq="${pendingScrollSeq}"]`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      setPendingScrollSeq(null)
    }
  }, [pendingScrollSeq, blocks])

  const minLoaded = Math.min(...loadedChunks)
  const maxLoaded = Math.max(...loadedChunks)
  const topLoading = ranges[0]?.index === minLoaded && spanQueries[0]?.isLoading
  const bottomLoading =
    ranges[ranges.length - 1]?.index === maxLoaded && spanQueries[spanQueries.length - 1]?.isLoading

  if (parseStatus.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <LoadingSpinner />
      </div>
    )
  }
  if (!parseStatus.isSuccess) {
    // Shouldn't normally be reachable — the Reader tab trigger is disabled
    // until parse status resolves — but degrade cleanly if it is.
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
        {t('sources.reader.notReady')}
      </div>
    )
  }

  let lastPage: number | undefined

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col">
      <div className="mb-2 flex flex-shrink-0 items-center gap-2">
        <ReaderOutline sections={sectionIndex} onJump={handleJump} />
      </div>
      <div ref={containerRef} className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div ref={topSentinelRef} className="h-1" />
        {topLoading && (
          <div className="flex justify-center py-2">
            <LoadingSpinner size="sm" />
          </div>
        )}
        <div className="chat-markdown prose prose-sm prose-neutral dark:prose-invert max-w-none break-words">
          {renderItems.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('sources.reader.empty')}</p>
          )}
          {renderItems.map((item) => {
            const page = readerItemPage(item)
            const showPageMarker = page != null && page !== lastPage
            if (page != null) lastPage = page
            return (
              <div key={readerItemKey(item)}>
                {showPageMarker && (
                  <div
                    aria-hidden="true"
                    className="not-prose my-3 flex items-center gap-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground"
                  >
                    <span className="rounded-full border border-border px-1.5 py-0.5">
                      {t('sources.reader.page').replace('{page}', String(page))}
                    </span>
                    <span className="h-px flex-1 bg-border" />
                  </div>
                )}
                <ReaderBlockItem item={item} />
              </div>
            )
          })}
        </div>
        {bottomLoading && (
          <div className="flex justify-center py-2">
            <LoadingSpinner size="sm" />
          </div>
        )}
        <div ref={bottomSentinelRef} className="h-1" />
      </div>
    </div>
  )
}
