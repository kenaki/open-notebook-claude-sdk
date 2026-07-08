import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { sourcesApi } from '@/lib/api/sources'
import type {
  Annotation,
  AnnotationRect,
  Block,
  PageBlocksResponse,
  ParseStatusResponse,
} from '@/lib/types/api'

/**
 * pdf-block-ingestion Track D3 — TanStack hooks over the C1 typed-block read
 * endpoints. These back the anchor-aware highlight UI (block context + parse
 * lifecycle) and are consumed by later chunks (D4 status chip, D6 reader).
 *
 * All three queries live UNDER the `['sources', id, …]` cache tree so a broad
 * `['sources']` invalidation (e.g. after a re-parse) refreshes them too, and a
 * never-parsed source's 404 is surfaced as a query error — never a toast
 * (`meta.silent`) — so the UI can render a "legacy / unparsed" affordance.
 */

// Parse statuses that are still in-flight — only these keep the poll alive.
const ACTIVE_PARSE_STATUSES = new Set(['pending', 'parsing', 'embedding'])

export const SOURCE_BLOCK_KEYS = {
  parse: (sourceId: string) => ['sources', sourceId, 'parse'] as const,
  pageBlocks: (sourceId: string, page: number) =>
    ['sources', sourceId, 'blocks', 'page', page] as const,
  block: (sourceId: string, seq: number) =>
    ['sources', sourceId, 'blocks', 'seq', seq] as const,
}

/**
 * Poll the parse status of a source's current generation. Returns the raw
 * TanStack result: `isSuccess` ⇒ the source is parsed (block reads are enabled);
 * `isError` ⇒ never parsed / 404 (render legacy UI). Polls every 3s ONLY while
 * the status is transient (pending/parsing/embedding), then stops.
 */
export function useParseStatus(
  sourceId?: string
): UseQueryResult<ParseStatusResponse> {
  return useQuery({
    queryKey: SOURCE_BLOCK_KEYS.parse(sourceId ?? ''),
    queryFn: () => sourcesApi.getParseStatus(sourceId as string),
    enabled: !!sourceId,
    // A never-parsed source 404s — that's an expected terminal state, not a
    // transient failure, so don't retry or toast it.
    retry: false,
    meta: { silent: true },
    refetchInterval: (query) => {
      const status = query.state.data?.parse_status
      return status && ACTIVE_PARSE_STATUSES.has(status) ? 3000 : false
    },
  })
}

/**
 * One page's blocks (overlay projection: seq/type/page/bbox) for hover /
 * block-selection affordances. Long-lived cache — a parsed generation is
 * immutable — so `staleTime: Infinity`. Enable only once the source is parsed
 * (pass `options.enabled`, typically `useParseStatus(...).isSuccess`).
 */
export function usePageBlocks(
  sourceId?: string,
  page?: number,
  options?: { enabled?: boolean }
): UseQueryResult<PageBlocksResponse> {
  const ready = !!sourceId && typeof page === 'number' && page >= 1
  return useQuery({
    queryKey: SOURCE_BLOCK_KEYS.pageBlocks(sourceId ?? '', page ?? 0),
    queryFn: () => sourcesApi.getPageBlocks(sourceId as string, page as number),
    enabled: ready && (options?.enabled ?? true),
    staleTime: Infinity,
    retry: false,
    meta: { silent: true },
  })
}

/**
 * A single full block (point-get with text/latex/section_path). Used by the
 * highlight popover to render an anchored annotation's section breadcrumb.
 * Enable only for a real seq on a parsed source.
 */
export function useBlock(
  sourceId?: string,
  seq?: number | null,
  options?: { enabled?: boolean }
): UseQueryResult<Block> {
  const ready = !!sourceId && typeof seq === 'number'
  return useQuery({
    queryKey: SOURCE_BLOCK_KEYS.block(sourceId ?? '', seq ?? -1),
    queryFn: () => sourcesApi.getBlock(sourceId as string, seq as number),
    enabled: ready && (options?.enabled ?? true),
    staleTime: Infinity,
    retry: false,
    meta: { silent: true },
  })
}

/**
 * Best-effort map a highlight's first rect (percent 0–100) to the overlay block
 * whose normalized bbox (0–1) contains the rect's center. Used as a fallback
 * "selected block" when an annotation carries no server-resolved `block_seq`
 * (e.g. a legacy highlight). Returns null when nothing matches.
 */
export function findBlockSeqForRect(
  blocks: Block[] | undefined,
  rects: AnnotationRect[] | undefined
): number | null {
  const rect = rects?.[0]
  if (!blocks || !rect) return null
  // Rect center as a page fraction (0–1).
  const cx = (rect.left + rect.width / 2) / 100
  const cy = (rect.top + rect.height / 2) / 100
  for (const block of blocks) {
    const b = block.bbox
    if (!b || b.length < 4) continue
    const [x0, y0, x1, y1] = b
    if (cx >= x0 && cx <= x1 && cy >= y0 && cy <= y1) return block.seq
  }
  return null
}

/**
 * The block seq a highlight should show context for: the server-resolved anchor
 * (`block_seq`) when present, else the geometric bbox match against `blocks`.
 */
export function selectedBlockSeq(
  annotation: Annotation | undefined,
  blocks: Block[] | undefined
): number | null {
  if (annotation?.block_seq != null) return annotation.block_seq
  return findBlockSeqForRect(blocks, annotation?.rect)
}
