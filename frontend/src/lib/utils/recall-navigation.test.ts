import { describe, it, expect, vi } from 'vitest'

import { navigateToRecallRef, type RecallNavContext } from './recall-navigation'
import type { RecallRef } from '@/lib/types/api'

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
  it('annotation on the currently-mounted source: requests a jump (no navigation)', () => {
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
  })

  it('annotation on a different source with no handler registered there: routes to that source page', () => {
    const ctx = makeCtx({ sourceId: 'source:current' })
    const ref: RecallRef = {
      ...baseRef,
      kind: 'annotation',
      source_id: 'source:other',
      annotation_id: 'source_annotation:ghi',
    }

    navigateToRecallRef(ref, ctx)

    expect(ctx.requestJump).toHaveBeenCalledWith('source:other', 'source_annotation:ghi')
    expect(ctx.push).toHaveBeenCalledWith('/sources/source:other')
  })

  it('annotation on a different source with a handler registered there (e.g. a workspace reader panel): jumps in place, no push', () => {
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
    expect(ctx.push).not.toHaveBeenCalled()
  })

  it('annotation with no current source in context (notebook chat) but a handler registered for the ref source: jumps in place, no push', () => {
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
    expect(ctx.push).not.toHaveBeenCalled()
  })

  it('annotation with no current source in context (notebook chat) and no handler registered: routes to the source page', () => {
    const ctx = makeCtx()
    const ref: RecallRef = {
      ...baseRef,
      kind: 'annotation',
      source_id: 'source:other',
      annotation_id: 'source_annotation:ghi',
    }

    navigateToRecallRef(ref, ctx)

    expect(ctx.requestJump).toHaveBeenCalledWith('source:other', 'source_annotation:ghi')
    expect(ctx.push).toHaveBeenCalledWith('/sources/source:other')
  })

  it('annotation missing both source id and annotation id is a no-op', () => {
    const ctx = makeCtx({ sourceId: 'source:abc' })
    navigateToRecallRef({ ...baseRef, kind: 'annotation' }, ctx)
    expect(ctx.push).not.toHaveBeenCalled()
    expect(ctx.requestJump).not.toHaveBeenCalled()
  })
})
