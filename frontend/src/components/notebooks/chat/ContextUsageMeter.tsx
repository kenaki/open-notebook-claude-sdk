'use client'

import { useMemo } from 'react'
import { Progress } from '@/components/ui/progress'
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/hooks/use-translation'
import { cn } from '@/lib/utils'
import { formatCompactNumber } from '@/lib/utils/format'
import type { NotebookChatMessage } from '@/lib/types/api'

// "82.0K" reads noisier than "82K" in a dense header row — trim the trailing
// ".0" that formatCompactNumber produces for round thousands/millions.
function formatTokens(n: number): string {
  return formatCompactNumber(n).replace(/\.0(?=[KM]$)/, '')
}

type UsageTone = 'default' | 'warning' | 'destructive'

interface ContextUsage {
  // Ground truth (contract #9): the last AI message carried a `usage` payload.
  exact: boolean
  // Tokens used — exact (input+output of the last reported turn) or estimated
  // (context payload + chars/4 across the message history).
  used: number
  // Model context window, when the backend reported one. Percent/bar render
  // only in this case — the window is unknowable client-side otherwise.
  window: number | null
  percent: number | null
  tone: UsageTone
}

// Derive the chat's context usage from its message stream. Ground truth wins:
// the LAST AI message with a non-null `usage` (claude-agent path) reports the
// real prompt+completion token counts. Otherwise estimate: the context
// payload's token count (from the existing token-count effect at the mount
// point — no second fetch loop) plus ~chars/4 over the message history.
function useContextUsage(
  messages: NotebookChatMessage[],
  contextTokens: number,
): ContextUsage {
  return useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i]
      if (m.type !== 'ai' || !m.usage) continue
      const used = (m.usage.input_tokens ?? 0) + (m.usage.output_tokens ?? 0)
      const window = m.usage.context_window ?? null
      const percent = window && window > 0 ? Math.round((used / window) * 100) : null
      const tone: UsageTone =
        percent === null ? 'default' : percent > 90 ? 'destructive' : percent >= 70 ? 'warning' : 'default'
      return { exact: true, used, window: window && window > 0 ? window : null, percent, tone }
    }
    const historyChars = messages.reduce((sum, m) => sum + m.content.length, 0)
    const used = Math.round(contextTokens + historyChars / 4)
    return { exact: false, used, window: null, percent: null, tone: 'default' }
  }, [messages, contextTokens])
}

const TONE_TEXT: Record<UsageTone, string> = {
  default: 'text-muted-foreground',
  warning: 'text-amber-600',
  destructive: 'text-destructive',
}

// Progress's indicator is hardcoded bg-primary; recolor it per tone via an
// arbitrary descendant variant (same trick as Button's svg sizing).
const TONE_BAR: Record<UsageTone, string> = {
  default: '',
  warning: '[&_[data-slot=progress-indicator]]:bg-amber-500',
  destructive: '[&_[data-slot=progress-indicator]]:bg-destructive',
}

interface ContextUsageMeterProps {
  // The chat's live message stream (the mount point already has it via
  // chat.getMessages) — scanned for the last AI `usage` payload.
  messages: NotebookChatMessage[]
  // Token count of the context payload from the existing token-count effect
  // (useBuildNotebookContext); the estimate fallback's context term. Pass 0
  // when the mount point has no applicable count.
  contextTokens: number
  className?: string
}

/**
 * Compact context-window usage meter for chat headers (chat-foundation N3).
 * Sits beside the dock's "N sources · M notes · k tokens" affordance and in
 * popped side-chat headers.
 *
 * Two modes:
 * - **Ground truth** — the last AI message carries `usage` (contract #9):
 *   "82K / 200K" with a percent + thin progress bar, toned by fullness
 *   (<70% default, 70–90% warning, >90% destructive). Without a reported
 *   `context_window`, just the exact used count (no percent, no bar).
 * - **Estimate** — no usage anywhere (local/Esperanto models): tilde-prefixed
 *   "~93K tokens in context" with no percent/bar — the window is unknown
 *   client-side and we deliberately don't mirror the backend's model→window map.
 */
export function ContextUsageMeter({ messages, contextTokens, className }: ContextUsageMeterProps) {
  const { t } = useTranslation()
  const usage = useContextUsage(messages, contextTokens)

  // A brand-new chat with nothing selected: an "~0 tokens" pill is just noise.
  if (!usage.exact && usage.used <= 0) return null

  const usedLabel = formatTokens(usage.used)

  let text: string
  let tooltip: string
  if (!usage.exact) {
    text = t('chat.contextMeterEstimate').replace('{used}', usedLabel)
    tooltip = t('chat.contextMeterTooltipEstimate')
  } else if (usage.window !== null && usage.percent !== null) {
    text = t('chat.contextMeterUsed')
      .replace('{used}', usedLabel)
      .replace('{window}', formatTokens(usage.window))
    tooltip = t('chat.contextMeterTooltipExact')
      .replace('{used}', usedLabel)
      .replace('{window}', formatTokens(usage.window))
      .replace('{percent}', usage.percent.toString())
  } else {
    text = t('chat.contextMeterUsedNoWindow').replace('{used}', usedLabel)
    tooltip = t('chat.contextMeterTooltipExactNoWindow')
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          className={cn(
            'flex flex-shrink-0 cursor-default items-center gap-1.5',
            className,
          )}
          aria-label={t('chat.contextMeterLabel')}
        >
          {usage.percent !== null && (
            <>
              <span className={cn('text-[11px] font-medium tabular-nums', TONE_TEXT[usage.tone])}>
                {usage.percent}%
              </span>
              <Progress
                value={Math.min(usage.percent, 100)}
                className={cn('h-1 w-12', TONE_BAR[usage.tone])}
              />
            </>
          )}
          <span className={cn('whitespace-nowrap text-[11px] tabular-nums', TONE_TEXT[usage.tone])}>
            {text}
          </span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-64">
        <p>{tooltip}</p>
      </TooltipContent>
    </Tooltip>
  )
}
