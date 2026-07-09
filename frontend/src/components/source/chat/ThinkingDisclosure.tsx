'use client'

import { Brain, ChevronRight } from 'lucide-react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { useTranslation } from '@/lib/hooks/use-translation'

/**
 * Collapsible "Thinking…" section for a completed AI message (agent-console
 * B3, coordinator Decision #2). Mirrors `ToolUseDisclosure`'s uncontrolled
 * Radix Collapsible idiom — closed by default, no external state.
 *
 * Renders plain prose (NOT ReactMarkdown, Q-thinking-md): the reasoning text
 * is often long and collapsed by default, so paying the KaTeX/rehype-highlight
 * parse cost for it would be wasted on content the user may never expand.
 */
export function ThinkingDisclosure({ thinking }: { thinking: string }) {
  const { t } = useTranslation()
  if (!thinking.trim()) return null

  return (
    <Collapsible className="w-full">
      <CollapsibleTrigger className="group flex w-full items-center gap-1.5 rounded-lg border border-border-2 bg-panel-2 px-2.5 py-1.5 text-left text-xs text-muted-foreground transition-colors hover:bg-accent-soft">
        <Brain className="h-3.5 w-3.5 flex-shrink-0 text-text-3" aria-hidden="true" />
        <span className="font-medium text-foreground">{t('chat.thinking')}</span>
        <ChevronRight
          className="ml-auto h-3.5 w-3.5 flex-shrink-0 text-text-3 transition-transform duration-[0.18s] group-data-[state=open]:rotate-90"
          aria-hidden="true"
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <p className="mt-1 whitespace-pre-wrap px-1 text-xs italic leading-snug text-muted-foreground">
          {thinking}
        </p>
      </CollapsibleContent>
    </Collapsible>
  )
}
