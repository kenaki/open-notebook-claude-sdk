import { describe, expect, it } from 'vitest'
import { buildOutlineTree } from './ReaderOutline'
import type { SectionIndexEntry } from '@/lib/types/api'

const entry = (seq: number, level: number, title: string): SectionIndexEntry => ({
  seq,
  level,
  title,
})

describe('buildOutlineTree', () => {
  it('nests sections under the chapter that precedes them', () => {
    const tree = buildOutlineTree([
      entry(1, 1, 'Ch 1'),
      entry(2, 2, 'Sec 1.1'),
      entry(3, 2, 'Sec 1.2'),
      entry(4, 1, 'Ch 2'),
      entry(5, 2, 'Sec 2.1'),
    ])

    expect(tree.map((n) => n.title)).toEqual(['Ch 1', 'Ch 2'])
    expect(tree[0].children.map((n) => n.title)).toEqual(['Sec 1.1', 'Sec 1.2'])
    expect(tree[1].children.map((n) => n.title)).toEqual(['Sec 2.1'])
  })

  it('nests deeper levels beneath their own parent section', () => {
    const tree = buildOutlineTree([
      entry(1, 1, 'Ch 1'),
      entry(2, 2, 'Sec 1.1'),
      entry(3, 3, 'Sub 1.1.1'),
      entry(4, 2, 'Sec 1.2'),
    ])

    const chapter = tree[0]
    expect(chapter.children.map((n) => n.title)).toEqual(['Sec 1.1', 'Sec 1.2'])
    expect(chapter.children[0].children.map((n) => n.title)).toEqual(['Sub 1.1.1'])
    expect(chapter.children[1].children).toEqual([])
  })

  it('keeps a section that precedes any chapter as a root rather than dropping it', () => {
    const tree = buildOutlineTree([entry(1, 2, 'Orphan'), entry(2, 1, 'Ch 1')])

    expect(tree.map((n) => n.title)).toEqual(['Orphan', 'Ch 1'])
  })

  it('handles a skipped level without inventing an intermediate node', () => {
    const tree = buildOutlineTree([entry(1, 1, 'Ch 1'), entry(2, 3, 'Deep')])

    expect(tree).toHaveLength(1)
    expect(tree[0].children.map((n) => n.title)).toEqual(['Deep'])
  })

  it('returns a flat list of roots when every entry is level 1 (no-TOC fallback)', () => {
    const tree = buildOutlineTree([entry(1, 1, 'A'), entry(2, 1, 'B'), entry(3, 1, 'C')])

    expect(tree).toHaveLength(3)
    expect(tree.every((n) => n.children.length === 0)).toBe(true)
  })

  it('returns nothing for an empty index', () => {
    expect(buildOutlineTree([])).toEqual([])
  })
})
