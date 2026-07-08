'use client'

import { useMemo } from 'react'
import katex from 'katex'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { Block } from '@/lib/types/api'

/**
 * pdf-block-ingestion Track D6 — the markdown reader's per-block renderer.
 *
 * Blocks arrive from `useBlockSpan` as a flat, seq-ordered list. This module
 * groups that flat list into renderable items (consecutive `list_item`s into
 * one `<ul>`, a `figure` with its linked `caption` block) and renders each
 * typed block. `page_header`/`page_footer` are dropped entirely (never a
 * renderable item).
 *
 * D7 depends on this DOM contract: EVERY rendered block element (each `<li>`
 * inside a list, each figure/figcaption, every other block) carries
 * `data-seq={seq}` so the reader-born selection capture can walk ancestor
 * `data-seq` elements to resolve a `(block_seq, block_end_seq)` range.
 */

export type ReaderRenderItem =
  | { kind: 'list'; items: Block[] }
  | { kind: 'figure'; block: Block; caption?: Block }
  | { kind: 'block'; block: Block }

/**
 * Groups a flat, seq-ordered block list into render items. Captions are
 * matched to their figure by `parent_seq` (docling_parser sets it at parse
 * time); an unmatched caption renders standalone. `page_header`/`page_footer`
 * blocks are dropped here so callers never see them.
 */
export function buildReaderRenderItems(blocks: Block[]): ReaderRenderItem[] {
  const items: ReaderRenderItem[] = []
  const consumedCaptions = new Set<number>()
  let i = 0
  while (i < blocks.length) {
    const block = blocks[i]

    if (consumedCaptions.has(block.seq)) {
      i++
      continue
    }
    if (block.type === 'page_header' || block.type === 'page_footer') {
      i++
      continue
    }
    if (block.type === 'list_item') {
      const group: Block[] = []
      while (i < blocks.length && blocks[i].type === 'list_item') {
        group.push(blocks[i])
        i++
      }
      items.push({ kind: 'list', items: group })
      continue
    }
    if (block.type === 'figure') {
      const captionIdx = blocks.findIndex(
        (candidate, j) => j > i && candidate.type === 'caption' && candidate.parent_seq === block.seq
      )
      const caption = captionIdx !== -1 ? blocks[captionIdx] : undefined
      if (caption) consumedCaptions.add(caption.seq)
      items.push({ kind: 'figure', block, caption })
      i++
      continue
    }
    items.push({ kind: 'block', block })
    i++
  }
  return items
}

/** The 1-indexed physical page a render item starts on (for gutter markers). */
export function readerItemPage(item: ReaderRenderItem): number | undefined {
  if (item.kind === 'list') return item.items[0]?.page
  return item.block.page
}

/** The seq a render item should be keyed/scrolled by (its first block's seq). */
export function readerItemKey(item: ReaderRenderItem): number {
  if (item.kind === 'list') return item.items[0]?.seq ?? -1
  return item.block.seq
}

const HEADING_TAGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] as const

function HeadingBlock({ block }: { block: Block }) {
  const level = Math.min(Math.max(block.level ?? 1, 1), 6)
  const Tag = HEADING_TAGS[level - 1]
  return (
    <Tag id={`block-${block.seq}`} data-seq={block.seq} className="scroll-mt-4">
      {block.text}
    </Tag>
  )
}

/** LaTeX → KaTeX HTML with an error-fallback to the raw source (Decision #7:
 * no server-side validation, so a bad/incomplete formula must degrade
 * gracefully instead of crashing the reader). */
function EquationBlock({ block }: { block: Block }) {
  const latex = block.latex ?? ''
  const rendered = useMemo(() => {
    try {
      return { html: katex.renderToString(latex, { throwOnError: true, displayMode: true }), ok: true as const }
    } catch {
      return { html: null, ok: false as const }
    }
  }, [latex])

  if (!rendered.ok) {
    return (
      <pre data-seq={block.seq} className="overflow-x-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs">
        {latex}
      </pre>
    )
  }
  return (
    <div
      data-seq={block.seq}
      className="overflow-x-auto py-1"
      dangerouslySetInnerHTML={{ __html: rendered.html as string }}
    />
  )
}

interface TableCell {
  text?: string
}

/** Best-effort HTML table from Docling's raw `table_data.grid` (an expanded
 * 2D cell grid — span repeats included, so no rowspan/colspan math needed).
 * Returns null when the shape doesn't match, so the caller can fall back to
 * rendering the markdown `text` docling already generated for this table. */
function renderGridTable(tableData: Record<string, unknown> | undefined): React.ReactNode | null {
  const grid = tableData?.grid
  if (!Array.isArray(grid) || grid.length === 0) return null
  const rows = grid as unknown[][]
  if (!rows.every((row) => Array.isArray(row))) return null
  return (
    <table>
      <tbody>
        {rows.map((row, ri) => (
          <tr key={ri}>
            {row.map((cell, ci) => {
              const text = typeof cell === 'string' ? cell : (cell as TableCell)?.text ?? ''
              return <td key={ci}>{text}</td>
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function TableBlock({ block }: { block: Block }) {
  const gridTable = renderGridTable(block.table_data)
  return (
    <div data-seq={block.seq} className="chat-markdown-table">
      {gridTable ?? (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.text || ''}</ReactMarkdown>
      )}
    </div>
  )
}

function FigureBlock({ block, caption }: { block: Block; caption?: Block }) {
  const { t } = useTranslation()
  return (
    <figure data-seq={block.seq} className="my-3">
      {block.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element -- backend-served crop, not a Next-optimizable asset
        <img
          src={block.image_url}
          alt={caption?.text || t('sources.reader.figureAlt')}
          loading="lazy"
          className="max-w-full rounded border border-border"
        />
      ) : (
        <div className="rounded border border-dashed border-border bg-muted/30 px-3 py-6 text-center text-xs text-muted-foreground">
          {t('sources.reader.figureMissing')}
        </div>
      )}
      {caption && (
        <figcaption data-seq={caption.seq} className="mt-1 text-xs italic text-muted-foreground">
          {caption.text}
        </figcaption>
      )}
    </figure>
  )
}

function BlockByType({ block }: { block: Block }) {
  switch (block.type) {
    case 'heading':
      return <HeadingBlock block={block} />
    case 'code':
      return (
        <pre data-seq={block.seq} className="overflow-x-auto rounded-md border border-border bg-muted/40 p-3">
          <code className="font-mono text-xs">{block.text}</code>
        </pre>
      )
    case 'table':
      return <TableBlock block={block} />
    case 'equation':
      return <EquationBlock block={block} />
    case 'footnote':
      return (
        <p data-seq={block.seq} className="text-xs text-muted-foreground">
          {block.text}
        </p>
      )
    case 'caption':
      // Only reached for an orphan caption (no matching figure in this span).
      return (
        <p data-seq={block.seq} className="text-xs italic text-muted-foreground">
          {block.text}
        </p>
      )
    case 'paragraph':
    default:
      return block.text ? <p data-seq={block.seq}>{block.text}</p> : null
  }
}

/** Renders one grouped item: a `<ul>` of list_items, a figure+caption pair, or
 * a single typed block. */
export function ReaderBlockItem({ item }: { item: ReaderRenderItem }) {
  if (item.kind === 'list') {
    return (
      <ul>
        {item.items.map((li) => (
          <li key={li.seq} data-seq={li.seq}>
            {li.text}
          </li>
        ))}
      </ul>
    )
  }
  if (item.kind === 'figure') {
    return <FigureBlock block={item.block} caption={item.caption} />
  }
  return <BlockByType block={item.block} />
}
