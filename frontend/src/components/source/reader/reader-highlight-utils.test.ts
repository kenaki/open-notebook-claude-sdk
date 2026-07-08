import { describe, it, expect } from 'vitest'
import type { Annotation } from '@/lib/types/api'
import {
  annotationCoversBlock,
  segmentText,
} from './reader-highlight-utils'

function annotation(partial: Partial<Annotation>): Annotation {
  return {
    id: partial.id ?? 'annotation:1',
    source_id: 'source:x',
    page: 1,
    rect: [],
    color: '#fde047',
    tags: [],
    anchor_state: 'anchored',
    created: '',
    updated: '',
    ...partial,
  }
}

describe('annotationCoversBlock', () => {
  it('covers seqs within an anchored block range', () => {
    const a = annotation({ block_seq: 3, block_end_seq: 5 })
    expect(annotationCoversBlock(a, 3)).toBe(true)
    expect(annotationCoversBlock(a, 4)).toBe(true)
    expect(annotationCoversBlock(a, 5)).toBe(true)
    expect(annotationCoversBlock(a, 2)).toBe(false)
    expect(annotationCoversBlock(a, 6)).toBe(false)
  })

  it('treats a single-block range with only block_seq set', () => {
    const a = annotation({ block_seq: 7, block_end_seq: null })
    expect(annotationCoversBlock(a, 7)).toBe(true)
    expect(annotationCoversBlock(a, 8)).toBe(false)
  })

  it('excludes stale/legacy and unanchored annotations', () => {
    expect(annotationCoversBlock(annotation({ block_seq: 1, anchor_state: 'stale' }), 1)).toBe(false)
    expect(annotationCoversBlock(annotation({ block_seq: 1, anchor_state: 'legacy' }), 1)).toBe(false)
    expect(annotationCoversBlock(annotation({ block_seq: null }), 1)).toBe(false)
  })
})

describe('segmentText', () => {
  it('returns one plain segment when nothing covers the block', () => {
    const segs = segmentText('hello world', 1, [])
    expect(segs).toEqual([{ text: 'hello world', annotation: null }])
  })

  it('paints an offset-precise slice for a single-block text anchor', () => {
    const a = annotation({ block_seq: 1, block_end_seq: 1, anchor_start: 6, anchor_end: 11 })
    const segs = segmentText('hello world', 1, [a])
    expect(segs).toEqual([
      { text: 'hello ', annotation: null },
      { text: 'world', annotation: a },
    ])
  })

  it('washes the whole block for a multi-block span (null offsets)', () => {
    const a = annotation({ block_seq: 1, block_end_seq: 3, anchor_start: null, anchor_end: null })
    const segs = segmentText('middle block', 2, [a])
    expect(segs).toEqual([{ text: 'middle block', annotation: a }])
  })

  it('washes the whole block when offsets are missing', () => {
    const a = annotation({ block_seq: 1, block_end_seq: 1 })
    const segs = segmentText('abc', 1, [a])
    expect(segs).toEqual([{ text: 'abc', annotation: a }])
  })

  it('lets a later annotation win overlapping pixels', () => {
    const first = annotation({ id: 'annotation:1', block_seq: 1, block_end_seq: 1, anchor_start: 0, anchor_end: 5, color: '#a' })
    const second = annotation({ id: 'annotation:2', block_seq: 1, block_end_seq: 1, anchor_start: 3, anchor_end: 8, color: '#b' })
    const segs = segmentText('0123456789', 1, [first, second])
    // 0..3 first, 3..8 second, 8..10 plain
    expect(segs.map((s) => [s.text, s.annotation?.id])).toEqual([
      ['012', 'annotation:1'],
      ['34567', 'annotation:2'],
      ['89', undefined],
    ])
  })
})
