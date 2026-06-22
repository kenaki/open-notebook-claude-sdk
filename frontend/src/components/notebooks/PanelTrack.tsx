'use client'

import { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface PanelTrackProps {
  children: ReactNode
  className?: string
}

/**
 * The horizontal, independently-scrolling row of panel cards that makes up the
 * notebook workspace (handoff "Panel track"). Children are {@link PanelCard}
 * wrappers around Sources / Notes / Chat dock / popped chats.
 *
 * Spec: `gap:16px`, `overflow-x:auto`. Track padding is supplied by the caller
 * (`px-6 pt-4 pb-[18px]` matches the handoff `16px 24px 18px`).
 */
export function PanelTrack({ children, className }: PanelTrackProps) {
  return (
    <div
      className={cn(
        'flex flex-row items-stretch gap-4 h-full min-h-0 overflow-x-auto',
        className
      )}
    >
      {children}
    </div>
  )
}
