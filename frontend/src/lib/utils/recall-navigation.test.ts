import { describe, it, expect, vi, beforeEach } from 'vitest'

import { navigateToRecallRef, type RecallNavContext } from './recall-navigation'
import { sendIntent } from '@/lib/sync/broadcast'
import type { RecallRef } from '@/lib/types/api'

// C4: the annotation branch now offers a local-miss jump to a PEER WINDOW via
// the sync bus before routing away. Mock the bus so we can drive the ack result.
vi.mock('@/lib/sync/broadcast', () => ({
  sendIntent: vi.fn(),
  INTENT_ANNOTATION_JUMP: 'annotation-jump',
}))

const mockedSendIntent = vi.mocked(sendIntent)

// The peer fallback is fire-and-forget (handled inside a `.then`), so tests must
// let microtasks + the resolved-promise continuation drain before asserting the
// push. A macrotask tick flushes both.
const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

beforeEach(() => {
  // Default: no peer window acks → the branch falls back to a push.
  mockedSendIntent.mockReset()
  mockedSendIntent.mockResolvedValue(false)
})

const baseRef: RecallRef = {
  kind: 'exchange',
  title: 'Discussing gradient descent',
  session_id: null,
  scope: null,
  source_id: null,
  notebook_id: null,
  message_id: null,
  annotation_id: null,
  page: null,
  quote: 'What is the learning rate?',
  similarity: 0.82,
}

function makeCtx(overrides: Partial<RecallNavContext> = {}) {
  return {
    push: vi.fn<RecallNavContext['push']>(),
    requestJump: vi.fn<RecallNavContext['requestJump']>(),
    ...overrides,
  }
}

describe('navigateToRecallRef — exchange refs', () => {
  it('same-source-chat exchange: switches the current chat surface in place (no navigation)', () => {
    const switchSession = vi.fn()
    const ctx = makeCtx({ sourceId: 'source:abc', switchSession })
    const ref: RecallRef = {
      ...baseRef,
      scope: 'source',
      source_id: 'source:abc',
      session_id: 'chat_session:same-src',
    }

    navigateToRecallRef(ref, ctx)

    expect(switchSession).toHaveBeenCalledWith('chat_session:same-src')
    expect(ctx.push).not.toHaveBeenCalled()
    expect(ctx.requestJump).not.toHaveBeenCalled()
  })

  it('same-source-chat exchange still matches when one side is a bare id (comparison is prefix-tolerant)', () => {
    const switchSession = vi.fn()
    const ctx = makeCtx({ sourceId: 'abc', switchSession })
    const ref: RecallRef = {
      ...baseRef,
      scope: 'source',
      source_id: 'source:abc',
      session_id: 'chat_session:same-src',
    }

    navigateToRecallRef(ref, ctx)

    expect(switchSession).toHaveBeenCalledWith('chat_session:same-src')
  })

  it('notebook-scope exchange: always routes via the notebook chat URL, regardless of current context', () => {
    const switchSession = vi.fn()
    const ctx = makeCtx({ sourceId: 'source:abc', switchSession })
    const ref: RecallRef = {
      ...baseRef,
      scope: 'notebook',
      notebook_id: 'notebook:xyz',
      session_id: 'chat_session:nb-sess',
    }

    navigateToRecallRef(ref, ctx)

    expect(ctx.push).toHaveBeenCalledWith('/notebooks/notebook:xyz/chat/chat_session:nb-sess')
    expect(switchSession).not.toHaveBeenCalled()
  })

  it('notebook-scope exchange routes even with no sourceId in context (e.g. from notebook chat itself)', () => {
    const ctx = makeCtx()
    const ref: RecallRef = {
      ...baseRef,
      scope: 'notebook',
      notebook_id: 'notebook:xyz',
      session_id: 'chat_session:nb-sess',
    }

    navigateToRecallRef(ref, ctx)

    expect(ctx.push).toHaveBeenCalledWith('/notebooks/notebook:xyz/chat/chat_session:nb-sess')
  })

  it('cross-source exchange (different source than the current one): routes to the source page', () => {
    const switchSession = vi.fn()
    const ctx = makeCtx({ sourceId: 'source:current', switchSession })
    const ref: RecallRef = {
      ...baseRef,
      scope: 'source',
      source_id: 'source:other',
      session_id: 'chat_session:other-sess',
    }

    navigateToRecallRef(ref, ctx)

    expect(ctx.push).toHaveBeenCalledWith('/sources/source:other')
    expect(switchSession).not.toHaveBeenCalled()
  })

  it('source-scope exchange with no switchSession available (e.g. notebook chat) falls back to the source page', () => {
    const ctx = makeCtx()
    const ref: RecallRef = {
      ...baseRef,
      scope: 'source',
      source_id: 'source:abc',
      session_id: 'chat_session:same-src',
    }

    navigateToRecallRef(ref, ctx)

    expect(ctx.push).toHaveBeenCalledWith('/sources/source:abc')
  })

  it('exchange with no source id and no notebook route is a no-op', () => {
    const ctx = makeCtx()
    navigateToRecallRef({ ...baseRef }, ctx)
    expect(ctx.push).not.toHaveBeenCalled()
    expect(ctx.requestJump).not.toHaveBeenCalled()
  })
})

describe('navigateToRecallRef — annotation refs', () => {
  it('annotation on the currently-mounted source: requests a jump (no navigation, no peer intent)', () => {
    const ctx = makeCtx({ sourceId: 'source:abc' })
    const ref: RecallRef = {
      ...baseRef,
      kind: 'annotation',
      source_id: 'source:abc',
      annotation_id: 'source_annotation:ghi',
    }

    navigateToRecallRef(ref, ctx)

    expect(ctx.requestJump).toHaveBeenCalledWith('source:abc', 'source_annotation:ghi')
    expect(ctx.push).not.toHaveBeenCalled()
    // The current source is mounted here, so we never reach the peer bus.
    expect(mockedSendIntent).not.toHaveBeenCalled()
  })

  it('annotation on a different source, no local handler and no peer ack: routes to that source page', async () => {
    const ctx = makeCtx({ sourceId: 'source:current' })
    const ref: RecallRef = {
      ...baseRef,
      kind: 'annotation',
      source_id: 'source:other',
      annotation_id: 'source_annotation:ghi',
    }

    navigateToRecallRef(ref, ctx)

    // Local miss → offer the jump to a peer window before routing.
    expect(ctx.requestJump).toHaveBeenCalledWith('source:other', 'source_annotation:ghi')
    expect(mockedSendIntent).toHaveBeenCalledWith('annotation-jump', {
      sourceId: 'source:other',
      annotationId: 'source_annotation:ghi',
    })
    // Push is fire-and-forget inside the ack promise — not yet.
    expect(ctx.push).not.toHaveBeenCalled()
    await flush()
    expect(ctx.push).toHaveBeenCalledWith('/sources/source:other')
  })

  it('annotation on a different source with a LOCAL handler (e.g. a workspace reader panel): jumps in place, no peer intent, no push', () => {
    const requestJump = vi.fn<RecallNavContext['requestJump']>().mockReturnValue(true)
    const ctx = makeCtx({ sourceId: 'source:current', requestJump })
    const ref: RecallRef = {
      ...baseRef,
      kind: 'annotation',
      source_id: 'source:other',
      annotation_id: 'source_annotation:ghi',
    }

    navigateToRecallRef(ref, ctx)

    expect(ctx.requestJump).toHaveBeenCalledWith('source:other', 'source_annotation:ghi')
    expect(mockedSendIntent).not.toHaveBeenCalled()
    expect(ctx.push).not.toHaveBeenCalled()
  })

  it('annotation with a local miss but a PEER WINDOW that acks the jump: no push', async () => {
    mockedSendIntent.mockResolvedValue(true)
    const ctx = makeCtx({ sourceId: 'source:current' })
    const ref: RecallRef = {
      ...baseRef,
      kind: 'annotation',
      source_id: 'source:other',
      annotation_id: 'source_annotation:ghi',
    }

    navigateToRecallRef(ref, ctx)

    expect(ctx.requestJump).toHaveBeenCalledWith('source:other', 'source_annotation:ghi')
    expect(mockedSendIntent).toHaveBeenCalledWith('annotation-jump', {
      sourceId: 'source:other',
      annotationId: 'source_annotation:ghi',
    })
    await flush()
    // A peer window handled the jump — we must NOT also navigate away here.
    expect(ctx.push).not.toHaveBeenCalled()
  })

  it('annotation with no current source in context (notebook chat) but a LOCAL handler for the ref source: jumps in place, no peer intent, no push', () => {
    const requestJump = vi.fn<RecallNavContext['requestJump']>().mockReturnValue(true)
    const ctx = makeCtx({ requestJump })
    const ref: RecallRef = {
      ...baseRef,
      kind: 'annotation',
      source_id: 'source:other',
      annotation_id: 'source_annotation:ghi',
    }

    navigateToRecallRef(ref, ctx)

    expect(ctx.requestJump).toHaveBeenCalledWith('source:other', 'source_annotation:ghi')
    expect(mockedSendIntent).not.toHaveBeenCalled()
    expect(ctx.push).not.toHaveBeenCalled()
  })

  it('annotation with no current source in context (notebook chat), no local handler and no peer ack: routes to the source page', async () => {
    const ctx = makeCtx()
    const ref: RecallRef = {
      ...baseRef,
      kind: 'annotation',
      source_id: 'source:other',
      annotation_id: 'source_annotation:ghi',
    }

    navigateToRecallRef(ref, ctx)

    expect(ctx.requestJump).toHaveBeenCalledWith('source:other', 'source_annotation:ghi')
    expect(mockedSendIntent).toHaveBeenCalled()
    await flush()
    expect(ctx.push).toHaveBeenCalledWith('/sources/source:other')
  })

  it('annotation missing both source id and annotation id is a no-op (no peer intent)', () => {
    const ctx = makeCtx({ sourceId: 'source:abc' })
    navigateToRecallRef({ ...baseRef, kind: 'annotation' }, ctx)
    expect(ctx.push).not.toHaveBeenCalled()
    expect(ctx.requestJump).not.toHaveBeenCalled()
    expect(mockedSendIntent).not.toHaveBeenCalled()
  })
})
