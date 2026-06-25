'use client'

import { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface PanelTrackProps {
  children: ReactNode
  className?: string
  /** Render the trailing scroll spacer. Off when a single panel fills the track
      (lone chat / maximized) so it doesn't leave a large empty gutter. */
  showSpacer?: boolean
}

/**
 * The horizontal, independently-scrolling row of panel cards that makes up the
 * notebook workspace (handoff "Panel track"). Children are {@link PanelCard}
 * wrappers around Sources / Notes / Chat dock / popped chats.
 *
 * Spec: `gap:16px`, `overflow-x:auto`. Track padding is supplied by the caller
 * (`px-6 pt-4 pb-[18px]` matches the handoff `16px 24px 18px`).
 */
export function PanelTrack({ children, className, showSpacer = true }: PanelTrackProps) {
  return (
    <div
      className={cn(
        'flex flex-row items-stretch gap-4 h-full min-h-0 overflow-x-auto overscroll-x-none snap-x snap-mandatory',
        className
      )}
    >
      {children}
      {/* Trailing spacer: gives the track scrollable room past the last panel so
          the row can be scrolled leftward even when the panels don't overflow.
          Invisible and non-interactive so it never intercepts drags/clicks. */}
      {showSpacer && (
        <div aria-hidden className="flex-shrink-0 w-[min(80vw,900px)] pointer-events-none" />
      )}
    </div>
  )
}
