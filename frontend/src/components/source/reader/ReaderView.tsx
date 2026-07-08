'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Clock, RotateCw } from 'lucide-react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useParseStatus, SOURCE_BLOCK_KEYS } from '@/lib/hooks/use-source-blocks'
import {
  useSourceAnnotations,
  useCreateAnnotation,
  useUpdateAnnotation,
  useDeleteAnnotation,
} from '@/lib/hooks/use-source-annotations'
import { sourcesApi } from '@/lib/api/sources'
import type { Annotation, Block } from '@/lib/types/api'
import { AnnotationHighlightPopover, DEFAULT_HIGHLIGHT_COLOR } from '@/components/source/detail/AnnotationHighlightPopover'
import {
  buildReaderRenderItems,
  readerItemKey,
  readerItemPage,
  ReaderBlockItem,
  ReaderHighlightContext,
} from './ReaderBlock'
import { ReaderOutline } from './ReaderOutline'
import { ReaderSelectionToolbar } from './ReaderSelectionToolbar'

/** Nearest ancestor element carrying a `data-seq` (D6's DOM contract), or null. */
function ancestorWithSeq(node: Node | null): HTMLElement | null {
  let el: HTMLElement | null =
    node instanceof HTMLElement ? node : node?.parentElement ?? null
  while (el && el.dataset?.seq === undefined) el = el.parentElement
  return el && el.dataset?.seq !== undefined ? el : null
}

/** Char offset of a DOM (node, offset) position within a block element's text —
 * sums the lengths of the text nodes preceding it. Offsets index the raw block
 * text (highlight `<mark>`s preserve the exact string), so they stay consistent
 * with the backend, which offsets into `block.text`. */
function offsetWithin(root: HTMLElement, node: Node, nodeOffset: number): number {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let total = 0
  let cur = walker.nextNode()
  while (cur) {
    if (cur === node) return total + nodeOffset
    total += cur.textContent?.length ?? 0
    cur = walker.nextNode()
  }
  return total
}

interface SelectionDraft {
  blockSeq: number
  blockEndSeq: number
  anchorStart: number | null
  anchorEnd: number | null
  quote: string
  top: number
  left: number
  atomic?: boolean
}

interface ActivePopover {
  annotation: Annotation
  top: number
  left: number
  noteMode?: boolean
}

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

export function ReaderView({
  sourceId,
  onChatAboutHighlight,
  onReprocess,
  jumpApiRef,
}: {
  sourceId: string
  /**
   * Optional "Ask AI about this passage" action (D8 wires it for reader↔chat
   * parity). Threaded into the selection toolbar + highlight popover; when
   * undefined the Ask-AI button hides itself, exactly like the PDF viewer.
   * The optional 2nd arg carries the annotation id (present for an existing
   * highlight's popover; absent for a fresh selection → quote fallback).
   */
  onChatAboutHighlight?: (quote: string, annotationId?: string) => void
  /**
   * D8: opens the same Re-process confirm dialog the header chip uses, so a
   * stale-highlight CTA inside the reader can trigger a re-anchor. Hidden when
   * undefined.
   */
  onReprocess?: () => void
  /**
   * D8 jump bridge: SourceDetailContent fills this ref with `handleJump` so a
   * chat reference pill can scroll the reader to a block while it's the active
   * tab.
   */
  jumpApiRef?: React.MutableRefObject<((seq: number) => void) | null>
}) {
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

  // --- Reader-born annotations (D7): inline render + selection create. ------ //
  const { data: annotations = [] } = useSourceAnnotations(sourceId)
  const createAnnotation = useCreateAnnotation(sourceId)
  const updateAnnotation = useUpdateAnnotation(sourceId)
  const deleteAnnotation = useDeleteAnnotation(sourceId)
  // Only anchored highlights render inline (stale/legacy are sidebar-only, §2.3).
  const anchoredAnnotations = useMemo(
    () => annotations.filter((a) => a.anchor_state === 'anchored' && a.block_seq != null),
    [annotations]
  )
  const allTags = useMemo(
    () => [...new Set(annotations.flatMap((a) => a.tags ?? []))],
    [annotations]
  )
  const [selDraft, setSelDraft] = useState<SelectionDraft | null>(null)
  const [activePopover, setActivePopover] = useState<ActivePopover | null>(null)

  // DOM text selection → a (block_seq, block_end_seq, offsets, quote) draft.
  const contentRef = useRef<HTMLDivElement>(null)
  const handleMouseUp = useCallback(() => {
    const sel = window.getSelection()
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) return
    const range = sel.getRangeAt(0)
    const root = contentRef.current
    if (!root || !root.contains(range.commonAncestorContainer)) return
    const startEl = ancestorWithSeq(range.startContainer)
    const endEl = ancestorWithSeq(range.endContainer)
    if (!startEl || !endEl) return
    const startSeq = Number(startEl.dataset.seq)
    const endSeq = Number(endEl.dataset.seq)
    if (Number.isNaN(startSeq) || Number.isNaN(endSeq)) return
    const quote = sel.toString()
    if (!quote.trim()) return

    const forward = startSeq <= endSeq
    const blockSeq = forward ? startSeq : endSeq
    const blockEndSeq = forward ? endSeq : startSeq
    let anchorStart: number | null = null
    let anchorEnd: number | null = null
    if (blockSeq === blockEndSeq) {
      // Single block → offset-precise; order the two DOM positions.
      const a = offsetWithin(startEl, range.startContainer, range.startOffset)
      const b = offsetWithin(endEl, range.endContainer, range.endOffset)
      anchorStart = Math.min(a, b)
      anchorEnd = Math.max(a, b)
    }
    const rect = range.getBoundingClientRect()
    setActivePopover(null)
    setSelDraft({
      blockSeq,
      blockEndSeq,
      anchorStart,
      anchorEnd,
      quote,
      top: rect.bottom + 6,
      left: rect.left,
    })
  }, [])

  // Whole-block selection of an atomic figure/table/equation (can't text-select).
  const handleAtomicSelect = useCallback((block: Block, e: React.MouseEvent) => {
    setActivePopover(null)
    setSelDraft({
      blockSeq: block.seq,
      blockEndSeq: block.seq,
      anchorStart: null,
      anchorEnd: null,
      quote: block.text ?? '',
      top: e.clientY + 6,
      left: e.clientX,
      atomic: true,
    })
  }, [])

  const handleAnnotationClick = useCallback((annotation: Annotation, e: React.MouseEvent) => {
    setSelDraft(null)
    setActivePopover({ annotation, top: e.clientY, left: e.clientX })
  }, [])

  const hl: ReaderHighlightContext = useMemo(
    () => ({
      annotations: anchoredAnnotations,
      onAnnotationClick: handleAnnotationClick,
      onAtomicSelect: handleAtomicSelect,
    }),
    [anchoredAnnotations, handleAnnotationClick, handleAtomicSelect]
  )

  const createFromDraft = useCallback(
    async (color: string) => {
      if (!selDraft) return null
      const created = await createAnnotation.mutateAsync({
        block_seq: selDraft.blockSeq,
        block_end_seq: selDraft.blockEndSeq,
        anchor_start: selDraft.anchorStart,
        anchor_end: selDraft.anchorEnd,
        quote: selDraft.quote,
        color,
      })
      window.getSelection()?.removeAllRanges()
      return created
    },
    [selDraft, createAnnotation]
  )

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

  // D8: hand `handleJump` to the parent so a chat pill can scroll the reader to
  // a block while the Reader tab is active.
  useEffect(() => {
    if (!jumpApiRef) return
    jumpApiRef.current = (seq: number) => {
      void handleJump(seq)
    }
    return () => {
      if (jumpApiRef) jumpApiRef.current = null
    }
  }, [jumpApiRef, handleJump])

  // D8 stale-highlight CTA: highlights anchored to an older parse generation
  // (§2.3) don't render inline; surface a count + a re-process action so the
  // user can re-anchor them (B5 re-anchors on reparse).
  const staleCount = useMemo(
    () => annotations.filter((a) => a.anchor_state === 'stale').length,
    [annotations]
  )

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
        {staleCount > 0 && onReprocess && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={onReprocess}
                className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 transition-colors hover:bg-amber-500/10 dark:text-amber-400"
              >
                <Clock className="h-3 w-3" aria-hidden="true" />
                {t('sources.reader.staleChip').replace('{count}', String(staleCount))}
                <RotateCw className="h-3 w-3" aria-hidden="true" />
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-56">{t('sources.reader.staleTip')}</TooltipContent>
          </Tooltip>
        )}
      </div>
      <div ref={containerRef} className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div ref={topSentinelRef} className="h-1" />
        {topLoading && (
          <div className="flex justify-center py-2">
            <LoadingSpinner size="sm" />
          </div>
        )}
        <div
          ref={contentRef}
          onMouseUp={handleMouseUp}
          className="chat-markdown prose prose-sm prose-neutral dark:prose-invert max-w-none break-words"
        >
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
                <ReaderBlockItem item={item} hl={hl} />
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

      {/* Reader-born selection toolbar: pick a color to highlight, add with a
          note, or Ask AI (D7). */}
      {selDraft && (
        <ReaderSelectionToolbar
          top={selDraft.top}
          left={selDraft.left}
          onClose={() => setSelDraft(null)}
          onPickColor={(color) => {
            createFromDraft(color)
              .then(() => setSelDraft(null))
              .catch(() => {
                /* mutation's error toast already surfaced the failure */
              })
          }}
          onNote={() => {
            createFromDraft(DEFAULT_HIGHLIGHT_COLOR)
              .then((created) => {
                setSelDraft(null)
                if (created) {
                  setActivePopover({
                    annotation: created,
                    top: selDraft.top,
                    left: selDraft.left,
                    noteMode: true,
                  })
                }
              })
              .catch(() => {
                /* mutation's error toast already surfaced the failure */
              })
          }}
          onAskAi={
            onChatAboutHighlight
              ? () => {
                  onChatAboutHighlight(selDraft.quote)
                  setSelDraft(null)
                  window.getSelection()?.removeAllRanges()
                }
              : undefined
          }
        />
      )}

      {/* Clicking an inline highlight opens the shared popover (note/color/tags/
          delete + optional Ask AI) — the same component the PDF tab uses. */}
      {activePopover && (
        <AnnotationHighlightPopover
          annotation={activePopover.annotation}
          top={activePopover.top}
          left={activePopover.left}
          sourceId={sourceId}
          blockSeq={activePopover.annotation.block_seq}
          startInNoteMode={activePopover.noteMode}
          allTags={allTags}
          onClose={() => setActivePopover(null)}
          onSaveNote={(note) => {
            updateAnnotation.mutate({ id: activePopover.annotation.id, data: { note } })
            setActivePopover(null)
          }}
          onChangeColor={(color) => {
            updateAnnotation.mutate({ id: activePopover.annotation.id, data: { color } })
            setActivePopover((prev) =>
              prev ? { ...prev, annotation: { ...prev.annotation, color } } : prev
            )
          }}
          onSaveTags={(tags) => {
            updateAnnotation.mutate({ id: activePopover.annotation.id, data: { tags } })
            setActivePopover((prev) =>
              prev ? { ...prev, annotation: { ...prev.annotation, tags } } : prev
            )
          }}
          onDelete={() => {
            deleteAnnotation.mutate(activePopover.annotation.id)
            setActivePopover(null)
          }}
          onChatAboutHighlight={
            onChatAboutHighlight
              ? (quote, annotationId) => {
                  onChatAboutHighlight(quote, annotationId)
                  setActivePopover(null)
                }
              : undefined
          }
        />
      )}
    </div>
  )
}
