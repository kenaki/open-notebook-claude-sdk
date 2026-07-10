'use client'

import { Minus, Plus, Type } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useTranslation } from '@/lib/hooks/use-translation'
import {
  READER_TYPOGRAPHY_BOUNDS,
  READER_TYPOGRAPHY_DEFAULTS,
  type ReaderTypography,
  type ReaderTypographyKey,
} from '@/lib/hooks/use-reader-typography'

/**
 * Reader text settings, sat in the reader toolbar beside the outline and page
 * nav. Body size, heading size and line spacing are separate knobs — heading
 * size scales the reader's heading ramp on its own, so a user who wants big
 * headings over compact body text (or the reverse) can have it.
 *
 * Steppers rather than sliders: the project carries no slider primitive, and a
 * one-step-per-click control is both keyboard-navigable for free and precise at
 * these narrow ranges.
 */

/** One labelled -/+ row. `format` renders the value for display. */
function StepperRow({
  settingKey,
  label,
  value,
  format,
  onChange,
}: {
  settingKey: ReaderTypographyKey
  label: string
  value: number
  format: (value: number) => string
  onChange: (key: ReaderTypographyKey, value: number) => void
}) {
  const { t } = useTranslation()
  const { min, max, step } = READER_TYPOGRAPHY_BOUNDS[settingKey]

  return (
    <div className="flex items-center justify-between gap-3">
      <span id={`reader-typography-${settingKey}`} className="text-xs text-muted-foreground">
        {label}
      </span>
      <div
        role="group"
        aria-labelledby={`reader-typography-${settingKey}`}
        className="flex items-center gap-1"
      >
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-6 w-6"
          disabled={value <= min}
          aria-label={t('sources.reader.typography.decrease').replace('{label}', label)}
          onClick={() => onChange(settingKey, value - step)}
        >
          <Minus className="h-3 w-3" aria-hidden="true" />
        </Button>
        {/* aria-live so a screen reader announces the new value on each step. */}
        <span aria-live="polite" className="w-12 text-center text-xs tabular-nums">
          {format(value)}
        </span>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-6 w-6"
          disabled={value >= max}
          aria-label={t('sources.reader.typography.increase').replace('{label}', label)}
          onClick={() => onChange(settingKey, value + step)}
        >
          <Plus className="h-3 w-3" aria-hidden="true" />
        </Button>
      </div>
    </div>
  )
}

export function ReaderTypographyMenu({
  typography,
  onChange,
  onReset,
}: {
  typography: ReaderTypography
  onChange: (key: ReaderTypographyKey, value: number) => void
  onReset: () => void
}) {
  const { t } = useTranslation()
  const isDefault =
    typography.fontSize === READER_TYPOGRAPHY_DEFAULTS.fontSize &&
    typography.headingScale === READER_TYPOGRAPHY_DEFAULTS.headingScale &&
    typography.lineHeight === READER_TYPOGRAPHY_DEFAULTS.lineHeight

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          aria-label={t('sources.reader.typography.label')}
        >
          <Type className="h-3.5 w-3.5" aria-hidden="true" />
          {t('sources.reader.typography.label')}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 space-y-3">
        <StepperRow
          settingKey="fontSize"
          label={t('sources.reader.typography.textSize')}
          value={typography.fontSize}
          format={(value) => `${value}px`}
          onChange={onChange}
        />
        <StepperRow
          settingKey="headingScale"
          label={t('sources.reader.typography.headingSize')}
          value={typography.headingScale}
          format={(value) => `${Math.round(value * 100)}%`}
          onChange={onChange}
        />
        <StepperRow
          settingKey="lineHeight"
          label={t('sources.reader.typography.lineSpacing')}
          value={typography.lineHeight}
          format={(value) => value.toFixed(1)}
          onChange={onChange}
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="w-full"
          disabled={isDefault}
          onClick={onReset}
        >
          {t('sources.reader.typography.reset')}
        </Button>
      </PopoverContent>
    </Popover>
  )
}
