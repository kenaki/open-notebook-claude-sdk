'use client'

import { useEffect, useId, useState } from 'react'
import mermaid from 'mermaid'
import DOMPurify from 'dompurify'
import { useTheme } from '@/lib/stores/theme-store'
import { CodeBlockShell } from './MarkdownCodeBlock'

// Renders a fenced ```mermaid``` block as a diagram, defensively:
//   - securityLevel: 'strict'  → mermaid sanitizes labels, disables click/JS.
//   - mermaid.parse(chart)     → validates syntax before rendering; throws on
//                                a bad diagram (also true mid-stream, while the
//                                fence is still incomplete).
//   - DOMPurify.sanitize(svg)  → second, independent scrub of the rendered SVG.
//   - On ANY throw → fall back to the normal code-block UI (never a red error
//     box); the raw source stays visible and copyable.
// Light/dark is driven by mermaid's `theme` from the app theme store.
export function Mermaid({ chart }: { chart: string }) {
  const { isDark } = useTheme()
  const [svg, setSvg] = useState<string | null>(null)
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>('loading')

  // Stable, DOM-safe id for mermaid.render's temporary element.
  const renderId = 'mermaid-' + useId().replace(/[^a-zA-Z0-9]/g, '')

  useEffect(() => {
    let cancelled = false
    setStatus('loading')

    const run = async () => {
      try {
        // Re-init each pass so a theme flip re-themes the diagram. `initialize`
        // is a cheap global config write; it's fine to call repeatedly.
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: isDark ? 'dark' : 'default',
        })
        // Validate first — throws on invalid / still-streaming syntax.
        await mermaid.parse(chart)
        const rendered = await mermaid.render(renderId, chart)
        const clean = DOMPurify.sanitize(rendered.svg, {
          // Allow the SVG (and any foreignObject HTML labels mermaid emits).
          USE_PROFILES: { svg: true, svgFilters: true, html: true },
        })
        if (!cancelled) {
          setSvg(clean)
          setStatus('ok')
        }
      } catch {
        if (!cancelled) {
          setSvg(null)
          setStatus('error')
        }
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [chart, isDark, renderId])

  // Any failure → the raw source through the shared code-block UI.
  if (status === 'error') {
    return (
      <CodeBlockShell language="mermaid" copyText={chart}>
        <code>{chart}</code>
      </CodeBlockShell>
    )
  }

  // While parsing/rendering (and during SSR-less first paint), show a slim
  // skeleton so there's never a jarring empty gap or a flash of source.
  if (status === 'loading' || svg == null) {
    return (
      <div
        className="chat-mermaid my-2 h-8 animate-pulse rounded bg-muted/40"
        aria-busy="true"
        aria-label="Rendering diagram"
      />
    )
  }

  return (
    <div
      className="chat-mermaid my-2 flex justify-center overflow-x-auto [&>svg]:h-auto [&>svg]:max-w-full"
      // SVG sanitized by DOMPurify above.
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
