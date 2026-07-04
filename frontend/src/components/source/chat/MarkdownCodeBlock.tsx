'use client'

import { useState, type ReactNode } from 'react'
import dynamic from 'next/dynamic'
import { Check, Copy } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'

// `mermaid` is browser-only (it reaches for `document` at render time), so load
// it lazily and client-side only — never during SSR (Q-C-mermaid-ssr). Loading
// it via next/dynamic also breaks the import cycle with ./Mermaid, which imports
// `CodeBlockShell` from this module for its fallback-to-codeblock render.
const Mermaid = dynamic(() => import('./Mermaid').then((m) => m.Mermaid), {
  ssr: false,
})

// hast node shape we care about (react-markdown passes the original node).
interface HastNode {
  type?: string
  value?: string
  tagName?: string
  properties?: { className?: string | string[] }
  children?: HastNode[]
}

// Walk the hast subtree and concatenate raw text — gives us the verbatim source
// to copy, independent of the highlighted <span> markup rehype-highlight injects.
function extractText(node?: HastNode): string {
  if (!node) return ''
  if (node.type === 'text') return node.value ?? ''
  return (node.children ?? []).map(extractText).join('')
}

// Pull the `language-xxx` token rehype-highlight leaves on the inner <code>.
function extractLanguage(node?: HastNode): string | null {
  const code = node?.children?.find((c) => c.tagName === 'code')
  const cls = code?.properties?.className
  const classes = Array.isArray(cls) ? cls : cls ? [cls] : []
  const lang = classes.find((c) => typeof c === 'string' && c.startsWith('language-'))
  return lang ? lang.replace('language-', '') : null
}

// The code-block chrome: a header bar (language label + copy button) over a
// <pre>. Shared so the Mermaid renderer's fallback-to-codeblock looks identical
// to a normal fenced block. `copyText` is the verbatim source the copy button
// writes; `children` is the <pre> body (the highlighted <code> for a normal
// block, or the raw source for the mermaid fallback).
export function CodeBlockShell({
  language,
  copyText,
  children,
}: {
  language: string | null
  copyText: string
  children?: ReactNode
}) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(copyText)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard unavailable — no-op, the code is still selectable */
    }
  }

  return (
    <div className="chat-codeblock">
      <div className="chat-codeblock-bar">
        <span className="chat-codeblock-lang">{language ?? 'text'}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="chat-codeblock-copy"
          title={t('common.copyToClipboard')}
          aria-label={t('common.copyToClipboard')}
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  )
}

// Fenced code block. A ```mermaid``` fence renders as a diagram (safely — with a
// fallback to this same code-block UI on any parse/render error); every other
// language renders as a normal highlighted code block. `children` is the
// already-rendered (highlighted) <code>.
export function MarkdownCodeBlock({
  node,
  children,
}: {
  node?: HastNode
  children?: ReactNode
}) {
  const language = extractLanguage(node)
  const source = extractText(node)

  if (language === 'mermaid') {
    return <Mermaid chart={source} />
  }

  return (
    <CodeBlockShell language={language} copyText={source}>
      {children}
    </CodeBlockShell>
  )
}
