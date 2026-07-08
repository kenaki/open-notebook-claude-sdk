import type { Annotation } from '@/lib/types/api'

/**
 * pdf-block-ingestion Track D7 — pure helpers for rendering inline highlights
 * in the markdown reader (db-design §2.3). Kept DB-free / DOM-free so they're
 * unit-testable; the React rendering (`HighlightableText`, atomic wash) and the
 * DOM selection capture live in ReaderBlock/ReaderView.
 *
 * Only `anchored` annotations render inline (stale/legacy are sidebar-only per
 * §2.3). A single-block text annotation paints its `[anchor_start, anchor_end]`
 * slice; a multi-block span or an atomic figure/table/equation washes the whole
 * block (offsets are null on those, matching the backend's block-granular shape).
 */

/** Atomic block types wash the whole block (no char offsets). Mirrors the
 * backend `anchor_match.ATOMIC_TYPES`. */
export const ATOMIC_BLOCK_TYPES = new Set(['figure', 'table', 'equation'])

/** True when an anchored annotation's block range covers this block seq. */
export function annotationCoversBlock(a: Annotation, seq: number): boolean {
  if (a.anchor_state !== 'anchored') return false
  if (a.block_seq == null) return false
  const end = a.block_end_seq ?? a.block_seq
  return seq >= a.block_seq && seq <= end
}

/** The anchored annotations that cover this block seq (render order = list order). */
export function annotationsForBlock(seq: number, annotations: Annotation[]): Annotation[] {
  return annotations.filter((a) => annotationCoversBlock(a, seq))
}

export interface TextSegment {
  text: string
  /** The annotation painting this segment, or null for un-highlighted text. */
  annotation: Annotation | null
}

/**
 * Splits a block's text into highlighted / plain segments for `seq`.
 *
 * For each covering annotation the painted range within THIS block is:
 *   - `[anchor_start, anchor_end]` when it's a single-block text anchor
 *     (`block_seq === block_end_seq === seq`) with in-bounds offsets;
 *   - the whole block `[0, len]` otherwise (multi-block span / atomic / missing
 *     offsets).
 * Overlaps are painted by a scan where a later annotation wins the pixel, so the
 * result is a flat, non-overlapping, gap-free segment list covering the text.
 */
export function segmentText(
  text: string,
  seq: number,
  annotations: Annotation[]
): TextSegment[] {
  const covering = annotationsForBlock(seq, annotations)
  if (text.length === 0 || covering.length === 0) {
    return [{ text, annotation: null }]
  }

  // Paint each char with the topmost (last-wins) covering annotation index.
  const paint: (number | null)[] = new Array(text.length).fill(null)
  covering.forEach((a, idx) => {
    let start = 0
    let end = text.length
    const single = a.block_seq === seq && (a.block_end_seq ?? a.block_seq) === seq
    if (single && a.anchor_start != null && a.anchor_end != null) {
      start = Math.max(0, a.anchor_start)
      end = Math.min(text.length, a.anchor_end)
    }
    for (let i = start; i < end; i++) paint[i] = idx
  })

  // Coalesce contiguous runs of the same paint value into segments.
  const segments: TextSegment[] = []
  let runStart = 0
  for (let i = 1; i <= text.length; i++) {
    if (i === text.length || paint[i] !== paint[runStart]) {
      const idx = paint[runStart]
      segments.push({
        text: text.slice(runStart, i),
        annotation: idx == null ? null : covering[idx],
      })
      runStart = i
    }
  }
  return segments
}
