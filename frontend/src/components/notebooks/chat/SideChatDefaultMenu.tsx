'use client'

import { Settings2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { FOLLOW_DEFAULT, useChatModelOptions } from './ChatModelPicker'
import { useTranslation } from '@/lib/hooks/use-translation'

interface SideChatDefaultMenuProps {
  // Current side-chat default model_override (null = follow the global default).
  value: string | null
  onChange: (model: string | null) => void
  // Per-notebook auto-illustrate toggle (chat-foundation F6), default ON.
  autoIllustrate: boolean
  onAutoIllustrateChange: (next: boolean) => void
}

/**
 * The dock header's settings cog: picks the per-notebook default model for side
 * chats (annotative sub-chats spawned from a passage), and (F6) the per-notebook
 * auto-illustrate toggle. Implemented as a single DropdownMenu rather than a
 * Popover-wrapped Select — nesting a Radix Select inside a Popover makes
 * selecting an item trip the Popover's outside-click and unmount the control
 * mid-pick, so the choice never lands.
 */
export function SideChatDefaultMenu({
  value,
  onChange,
  autoIllustrate,
  onAutoIllustrateChange,
}: SideChatDefaultMenuProps) {
  const { t } = useTranslation()
  const { followDefaultLabel, claudeSubmodels, localModels } = useChatModelOptions()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground"
          title={t('chat.chatSettings')}
        >
          <Settings2 className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>{t('chat.sideChatDefault')}</DropdownMenuLabel>
        <p className="px-2 pb-1.5 text-[11px] leading-snug text-muted-foreground">
          {t('chat.sideChatDefaultHelper')}
        </p>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={value ?? FOLLOW_DEFAULT}
          onValueChange={(v) => onChange(v === FOLLOW_DEFAULT ? null : v)}
        >
          <DropdownMenuRadioItem value={FOLLOW_DEFAULT}>
            {followDefaultLabel}
          </DropdownMenuRadioItem>
          {claudeSubmodels.map((opt) => (
            <DropdownMenuRadioItem key={opt.value} value={opt.value}>
              {opt.label}
            </DropdownMenuRadioItem>
          ))}
          {localModels.length > 0 && <DropdownMenuSeparator />}
          {localModels.map((opt) => (
            <DropdownMenuRadioItem key={opt.value} value={opt.value}>
              {opt.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t('chat.autoIllustrate')}</DropdownMenuLabel>
        <p className="px-2 pb-1.5 text-[11px] leading-snug text-muted-foreground">
          {t('chat.autoIllustrateHelper')}
        </p>
        <DropdownMenuCheckboxItem
          checked={autoIllustrate}
          onCheckedChange={onAutoIllustrateChange}
          onSelect={(e) => e.preventDefault()}
        >
          {t('chat.autoIllustrate')}
        </DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
