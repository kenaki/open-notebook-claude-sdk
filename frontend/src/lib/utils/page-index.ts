/**
 * Lookups over a parse header's `page_index` — the `page -> [first_seq, last_seq]`
 * list written by `open_notebook/parsers/base.py::finalize` and served on
 * `ParseStatusResponse`. Index `i` describes page `i + 1`.
 *
 * Blocks are numbered in reading order, so the ranges ascend and never overlap.
 * A page with no blocks stores the inverted sentinel range `[0, -1]`; compacting
 * those away up front is what keeps the search below a plain binary search.
 *
 * This gives the reader both directions it needs without touching the network:
 * seq -> page (labelling outline entries) and page -> seq (jump-to-page).
 */

/** A page with no blocks: `lo > hi` (the sentinel is `[0, -1]`). */
function isEmptyRange(range: number[] | undefined): boolean {
  return !range || range.length < 2 || range[0] > range[1]
}

/** One page that actually holds blocks. */
interface PageSpan {
  page: number // 1-based
  lo: number
  hi: number
}

/**
 * Compacted, ascending spans for the pages that hold blocks. Build once per
 * parse generation (`useMemo` on `page_index`) and reuse across lookups.
 */
export function buildPageSpans(pageIndex: number[][] | undefined): PageSpan[] {
  if (!pageIndex?.length) return []
  const spans: PageSpan[] = []
  for (let i = 0; i < pageIndex.length; i++) {
    const range = pageIndex[i]
    if (isEmptyRange(range)) continue
    spans.push({ page: i + 1, lo: range[0], hi: range[1] })
  }
  return spans
}

/**
 * The 1-based page containing `seq`, or null when it falls in no page's range
 * (an unparsed source, or a stale seq from a prior parse generation).
 */
export function pageForSeq(spans: PageSpan[], seq: number): number | null {
  if (!spans.length || !Number.isFinite(seq)) return null
  let lo = 0
  let hi = spans.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const span = spans[mid]
    if (seq < span.lo) hi = mid - 1
    else if (seq > span.hi) lo = mid + 1
    else return span.page
  }
  return null
}

/**
 * The first block seq at or after `page` (1-based). A blank page falls through
 * to the next page that has blocks, so jumping to one lands on the next real
 * content rather than nowhere. Null when nothing follows.
 */
export function firstSeqFromPage(spans: PageSpan[], page: number): number | null {
  for (const span of spans) {
    if (span.page >= page) return span.lo
  }
  return null
}

/** Clamp a (possibly user-typed) page into `[1, pageCount]`; null if unusable. */
export function clampPage(page: number, pageCount: number): number | null {
  if (!Number.isFinite(page) || pageCount < 1) return null
  return Math.min(Math.max(Math.trunc(page), 1), pageCount)
}

/**
 * The reader's loaded-chunk window after `chunkIndex` is requested.
 *
 * The window MUST stay contiguous. Blocks from every loaded chunk render as one
 * seq-ordered list, so a disjoint window ({0, 99}) splices the end of chunk 0
 * directly above the start of chunk 99 — page 10 sits against page 991, the
 * reader silently skips 980 pages, and scrolling up from the jump target
 * reports page 10. The scroll sentinels can't repair it: they only ever extend
 * the window by one chunk past its current min/max.
 *
 * So an adjacent chunk grows the window, and a far jump relocates it — the
 * sentinels then refill outwards from wherever the user landed.
 */
export function nextChunkWindow(prev: number[], chunkIndex: number): number[] {
  if (prev.length === 0) return [chunkIndex]
  if (prev.includes(chunkIndex)) return prev
  const min = Math.min(...prev)
  const max = Math.max(...prev)
  if (chunkIndex === min - 1 || chunkIndex === max + 1) return [...prev, chunkIndex]
  return [chunkIndex]
}
