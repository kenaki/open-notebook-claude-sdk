import type { RecallRef } from '@/lib/types/api'

/**
 * Comparison-only normalizer: strips a SurrealDB record's table prefix so two
 * ids can be compared for "same record" even if one side happens to be bare.
 * This repo's ids flow as FULL records ("chat_session:...", "source:...")
 * everywhere they're actually consumed by switchSession / requestJump /
 * router.push — verified against `SessionManager` (`session.id` passed
 * straight to `onSelectSession`), the D8 annotation-jump wiring
 * (`MessageList`'s `requestJump(sourceId, ref.id)`, `SourceDetailContent`'s
 * `registerJump(sourceId, ...)`), `ChatGallery.enterChat(session.id)`, and
 * `NotebookRow`'s `router.push('/notebooks/${notebook.id}')` — none of them
 * strip the prefix. So this helper is ONLY for equality checks; the values
 * actually passed to those calls below are the raw contract fields.
 */
function sameRecord(a?: string | null, b?: string | null): boolean {
  if (!a || !b) return false
  const bare = (id: string) => id.replace(/^[^:]+:/, '')
  return bare(a) === bare(b)
}

export interface RecallNavContext {
  /** The current source-chat page's own source id (full record id). Absent in notebook chat — there is no "current source" there. */
  sourceId?: string
  /** Switches THIS chat surface to another of its own sessions in place (e.g. `useSourceChat().switchSession`). Only used for the same-source-chat exchange branch. */
  switchSession?: (sessionId: string) => void
  /** `useAnnotationJumpStore().requestJump` — no-op (returns false) if that source isn't mounted. */
  requestJump: (sourceId: string, annotationId: string) => boolean
  /** `next/navigation` router's `push`. */
  push: (path: string) => void
}

/**
 * Resolves a recall-pill click (study-memory Track C2) into a navigation
 * action, per the coordinator's P-nav-depth decision: SESSION-LEVEL only —
 * this never scrolls to a specific message, only opens/switches a session or
 * navigates to a source.
 *
 * Branch table (coordinator.md RecallRef contract + c-frontend.md Chunk C2):
 *  - exchange, same source chat (scope='source', source matches current) →
 *    switch the current chat surface to that session in place.
 *  - exchange, notebook scope → always route (`/notebooks/{nb}/chat/{sess}`);
 *    this works from anywhere, including from a source page, so there's no
 *    "same notebook" special case.
 *  - exchange, anything else (cross-source, or scope missing) → route to
 *    that source's detail page if we at least have a source id.
 *  - annotation, same source mounted (`ctx.sourceId`) → `requestJump`.
 *  - annotation, otherwise → TRY a jump for the ref's own source first (e.g. a
 *    workspace reader panel has that source mounted even though it isn't
 *    `ctx.sourceId`); only if no handler is registered (`requestJump` returns
 *    false, P-jump-bool) fall back to routing to that source's detail page.
 */
export function navigateToRecallRef(ref: RecallRef, ctx: RecallNavContext): void {
  if (ref.kind === 'exchange') {
    if (
      ref.scope === 'source' &&
      ref.session_id &&
      ctx.switchSession &&
      sameRecord(ref.source_id, ctx.sourceId)
    ) {
      ctx.switchSession(ref.session_id)
      return
    }
    if (ref.scope === 'notebook' && ref.notebook_id && ref.session_id) {
      ctx.push(`/notebooks/${ref.notebook_id}/chat/${ref.session_id}`)
      return
    }
    if (ref.source_id) {
      ctx.push(`/sources/${ref.source_id}`)
    }
    return
  }

  if (ref.kind === 'annotation') {
    if (ref.annotation_id && ctx.sourceId && sameRecord(ref.source_id, ctx.sourceId)) {
      ctx.requestJump(ctx.sourceId, ref.annotation_id)
      return
    }
    if (ref.annotation_id && ref.source_id && ctx.requestJump(ref.source_id, ref.annotation_id)) {
      return
    }
    if (ref.source_id) {
      ctx.push(`/sources/${ref.source_id}`)
    }
  }
}
