'use client'

import { useMemo } from 'react'
import { Cpu } from 'lucide-react'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useClaudeAgentModel, useModels } from '@/lib/hooks/use-models'
import { useTranslation } from '@/lib/hooks/use-translation'
import { cn } from '@/lib/utils'

// Radix Select forbids an empty-string item value; the claude-agent "follow
// Claude Code default" option uses '' on the wire, so we map it to this sentinel.
export const FOLLOW_DEFAULT = '__default__'

// Per-chat Claude Agent override marker; mirrors CLAUDE_AGENT_OVERRIDE_PREFIX in
// open_notebook/ai/claude_agent.py (and ModelSelector.tsx). A value of
// "claude_agent::<model>" pins that Claude model for this chat only; a bare
// registered model id (e.g. "model:...") routes the chat through Esperanto.
export const CLAUDE_AGENT_OVERRIDE_PREFIX = 'claude_agent::'

export interface ChatModelOption {
  value: string
  label: string
}

export interface ChatModelOptions {
  // Label for the "follow the global Claude default" sentinel entry.
  followDefaultLabel: string
  // Claude Agent sub-models, values prefixed with CLAUDE_AGENT_OVERRIDE_PREFIX.
  claudeSubmodels: ChatModelOption[]
  // Locally-registered Esperanto language models.
  localModels: ChatModelOption[]
}

/**
 * The grouped model choices shared by every per-chat model control (the inline
 * {@link ChatModelPicker} and the dock's side-chat default menu). Mirrors
 * ModelSelector.tsx / claude_agent.py: Claude sub-models carry the
 * `claude_agent::` marker; local models use their bare registered id.
 */
export function useChatModelOptions(): ChatModelOptions {
  const { t } = useTranslation()
  const { data: claudeConfig } = useClaudeAgentModel()
  const { data: models } = useModels()

  const claudeSubmodels = (claudeConfig?.options ?? [])
    .filter((opt) => opt.value)
    .map((opt) => ({ value: `${CLAUDE_AGENT_OVERRIDE_PREFIX}${opt.value}`, label: opt.label }))
  const followDefaultLabel =
    (claudeConfig?.options ?? []).find((opt) => !opt.value)?.label ?? t('chat.model')

  const localModels = useMemo(
    () =>
      [...(models ?? [])]
        .filter((m) => m.type === 'language' && m.provider !== 'claude_agent')
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((m) => ({ value: m.id, label: m.name })),
    [models]
  )

  return { followDefaultLabel, claudeSubmodels, localModels }
}

interface ChatModelPickerProps {
  // The chat's current model_override (null/undefined = follow the global default).
  value: string | null
  // Receives the chosen override; null means "follow the global default".
  onChange: (model: string | null) => void
  disabled?: boolean
  // Compact icon-style trigger for cramped headers (popped chat panels). The
  // dock header uses the roomier default.
  compact?: boolean
  className?: string
}

/**
 * The per-chat model picker, shared by the dock header and every popped chat
 * panel so each conversation can run on its own model. The trigger surfaces the
 * actively-used model (via the selected item's label); the dropdown groups the
 * Claude Agent sub-models and the locally-registered Esperanto models. Both
 * groups + the "follow default" sentinel mirror ChatDock's original inline
 * picker (and ModelSelector.tsx / claude_agent.py on the backend).
 */
export function ChatModelPicker({
  value,
  onChange,
  disabled,
  compact = false,
  className,
}: ChatModelPickerProps) {
  const { t } = useTranslation()
  const { followDefaultLabel, claudeSubmodels, localModels } = useChatModelOptions()

  const selectValue = value ?? FOLLOW_DEFAULT

  return (
    <Select
      value={selectValue}
      onValueChange={(v) => onChange(v === FOLLOW_DEFAULT ? null : v)}
      disabled={disabled}
    >
      <SelectTrigger
        size="sm"
        title={t('chat.model')}
        className={cn(
          compact
            ? 'h-7 w-auto max-w-[150px] gap-1 border-none bg-transparent px-1.5 text-[11px] text-muted-foreground shadow-none hover:bg-accent'
            : 'h-8 max-w-[60%] gap-1.5 text-xs',
          className
        )}
      >
        <Cpu className="h-3.5 w-3.5 flex-shrink-0" />
        <SelectValue placeholder={t('chat.model')} />
      </SelectTrigger>
      {/* Dropdown rise-in tuned to the handoff's .14s (onb-up) — the shadcn
          Select already ships the slide+fade entrance. */}
      <SelectContent className="duration-150">
        <SelectGroup>
          <SelectLabel>{t('chat.modelGroupClaude')}</SelectLabel>
          <SelectItem value={FOLLOW_DEFAULT}>{followDefaultLabel}</SelectItem>
          {claudeSubmodels.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectGroup>
        {localModels.length > 0 && (
          <SelectGroup>
            <SelectLabel>{t('chat.modelGroupLocal')}</SelectLabel>
            {localModels.map((model) => (
              <SelectItem key={model.value} value={model.value}>
                {model.label}
              </SelectItem>
            ))}
          </SelectGroup>
        )}
      </SelectContent>
    </Select>
  )
}
