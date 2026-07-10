'use client'

import { useEffect } from 'react'
import {
  onIntent,
  INTENT_ANNOTATION_JUMP,
  type AnnotationJumpIntent,
} from '@/lib/sync/broadcast'
import { useAnnotationJumpStore } from '@/lib/stores/annotation-jump-store'

/**
 * Per-window receiver for cross-window intents that aren't tied to a specific
 * screen's React state (cross-interface-study / Chunk C4). Mounted ONCE per
 * window from the dashboard layout — in BOTH the full-chrome and the focus-mode
 * (`?focus=1`) branches — so every window, including a chromeless reader
 * pop-out, can service an `annotation-jump` from a peer. Renders nothing.
 *
 * `annotation-jump`: route straight into the per-source annotation-jump store.
 * `requestJump` returns true iff some mounted reader (SourceDetailContent /
 * SourceReaderPanel) registered a handler for that source — that boolean IS the
 * ack, so a window without the source simply declines and the sender falls back
 * to routing (recall-navigation.ts). No OS focus is forced (browsers ignore it
 * without a user gesture — P-focus-selffocus, accepted).
 *
 * The ask-AI intent is NOT handled here: it needs the notebook's active dock
 * chat, so its receiver lives in DeepDiveWorkspace where that state exists.
 */
export function CrossWindowRuntime() {
  useEffect(() => {
    return onIntent(INTENT_ANNOTATION_JUMP, (data) => {
      const { sourceId, annotationId } = data as AnnotationJumpIntent
      return useAnnotationJumpStore.getState().requestJump(sourceId, annotationId)
    })
  }, [])

  return null
}
