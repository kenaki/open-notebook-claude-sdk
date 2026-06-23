'use client'

import { ReactNode, useRef, useEffect, useCallback, useState } from 'react'
import { GripHorizontal } from 'lucide-react'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { cn } from '@/lib/utils'
import { PANEL_MIN_WIDTH, PANEL_MAX_WIDTH } from '@/lib/stores/notebook-columns-store'

interface PanelCardProps {
  /** Stable sortable id (panel id or popped chat session id). */
  id: string
  /** Computed CSS `order` for the display-order algorithm. */
  order?: number
  /** Current panel width in px (ignored when `minimized` or `maximized`). */
  width: number
  /** Called while dragging the right-edge resize handle. */
  onWidthChange?: (width: number) => void
  /** Panel is collapsed to a chip — child renders its own narrow chip; no resize. */
  minimized?: boolean
  /** This panel is the one currently maximized (flexes to fill the track). */
  maximized?: boolean
  /** Toggle maximize for this panel (double-click on a non-interactive area). */
  onToggleMaximize?: () => void
  resizable?: boolean
  /** Enable the left-edge drag-to-reorder grip (default true). */
  draggable?: boolean
  /** Smoothly scroll this panel into view on mount (e.g. a freshly-spawned side chat). */
  scrollIntoViewOnMount?: boolean
  className?: string
  children: ReactNode
}

/**
 * Track-level chrome around a workspace panel: fixed pixel width, a left-edge
 * drag-to-reorder grip (@dnd-kit sortable), a right-edge drag-to-resize handle
 * (clamped 240–980px), and double-click-to-maximize. The panel's own visual
 * shell (border / radius / shadow) comes from the child card (Sources / Notes /
 * Chat / popped chat).
 *
 * Must be rendered inside a {@link DndContext} + {@link SortableContext} (the
 * notebook page provides both). Visibility under maximize is decided by the
 * page (it simply doesn't render hidden cards), so this component never returns
 * null — keeping the sortable `items` list in sync with what's mounted.
 */
export function PanelCard({
  id,
  order,
  width,
  onWidthChange,
  minimized = false,
  maximized = false,
  onToggleMaximize,
  resizable = true,
  draggable = true,
  scrollIntoViewOnMount = false,
  className,
  children,
}: PanelCardProps) {
  const drag = useRef<{ startX: number; startWidth: number } | null>(null)
  // While the right-edge resize handle is held, width must track the pointer
  // 1:1 (no easing); the maximize/restore size change, by contrast, should ease.
  const [isResizing, setIsResizing] = useState(false)
  const { setNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({ id })

  // Combine dnd-kit's node ref with our own so we can scroll the panel into view.
  const nodeRef = useRef<HTMLDivElement | null>(null)
  const setRefs = useCallback(
    (el: HTMLDivElement | null) => {
      setNodeRef(el)
      nodeRef.current = el
    },
    [setNodeRef]
  )

  // Bring a freshly-spawned panel (e.g. a new side chat) into view, snapping it
  // to the left edge of the track with the same smooth animation as a manual scroll.
  useEffect(() => {
    if (scrollIntoViewOnMount) {
      nodeRef.current?.scrollIntoView({ behavior: 'smooth', inline: 'start', block: 'nearest' })
    }
  }, [scrollIntoViewOnMount])

  const handlePointerDown = (e: React.PointerEvent) => {
    if (!onWidthChange) return
    drag.current = { startX: e.clientX, startWidth: width }
    setIsResizing(true)
    e.currentTarget.setPointerCapture(e.pointerId)
    e.preventDefault()
  }

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!drag.current || !onWidthChange) return
    const delta = e.clientX - drag.current.startX
    const next = Math.max(
      PANEL_MIN_WIDTH,
      Math.min(PANEL_MAX_WIDTH, drag.current.startWidth + delta)
    )
    onWidthChange(next)
  }

  const endDrag = (e: React.PointerEvent) => {
    if (!drag.current) return
    drag.current = null
    setIsResizing(false)
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
  }

  const handleDoubleClick = (e: React.MouseEvent) => {
    if (minimized || !onToggleMaximize) return
    // Don't hijack double-clicks on controls or text selection.
    const target = e.target as HTMLElement
    if (
      target.closest(
        'button, a, input, textarea, select, [role="button"], [contenteditable="true"]'
      )
    ) {
      return
    }
    if (window.getSelection()?.toString()) return
    onToggleMaximize()
  }

  // Ease the maximize/restore size change (flex ⇄ fixed width). Suppressed while
  // resize-dragging (width must follow the pointer) and while sort-dragging (dnd-kit
  // owns the transform transition there). Composes with dnd-kit's `transition`.
  const sizeTransition =
    !isResizing && !isDragging ? 'flex 0.25s ease, width 0.25s ease' : undefined
  const style: React.CSSProperties = {
    order,
    transform: CSS.Transform.toString(transform),
    transition: [transition, sizeTransition].filter(Boolean).join(', ') || undefined,
    zIndex: isDragging ? 40 : undefined,
    opacity: isDragging ? 0.85 : undefined,
    ...(maximized
      ? { flex: '1 1 0%', minWidth: 0 }
      : minimized
        ? { flexShrink: 0 }
        : { width, flexShrink: 0 }),
  }

  const showResize = resizable && !maximized && !minimized && !!onWidthChange
  const showGrip = draggable && !maximized

  return (
    <div
      ref={setRefs}
      className={cn('group relative h-full min-h-0 flex flex-col snap-start snap-always', className)}
      style={style}
      onDoubleClick={handleDoubleClick}
    >
      {children}
      {showGrip && (
        <button
          type="button"
          {...attributes}
          {...listeners}
          aria-label="Reorder panel"
          className="absolute top-0 left-0 z-20 flex h-4 w-full cursor-grab touch-none items-center justify-center opacity-0 transition-opacity group-hover:opacity-100 active:cursor-grabbing"
        >
          <GripHorizontal className="h-4 w-4 text-text-3" />
        </button>
      )}
      {showResize && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize panel"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          className="absolute top-0 right-0 z-20 h-full w-1.5 cursor-col-resize touch-none rounded-full transition-colors hover:bg-primary/40"
        />
      )}
    </div>
  )
}
