'use client'

import { useState, type ReactNode } from 'react'
import { Check, Copy } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'

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

// Fenced code block: a header bar (language label + copy button) over the
// highlighted <pre>. `children` is the already-rendered (highlighted) <code>.
export function MarkdownCodeBlock({
  node,
  children,
}: {
  node?: HastNode
  children?: ReactNode
}) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const language = extractLanguage(node)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(extractText(node))
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
