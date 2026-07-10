import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * In-process BroadcastChannel double. Delivers each posted message
 * synchronously to every OTHER live instance of the same channel name (never
 * to the poster) — mirroring real BroadcastChannel semantics, which lets us
 * simulate multiple "windows" deterministically in one process.
 */
class MockBroadcastChannel {
  static channels: MockBroadcastChannel[] = []
  static reset() {
    MockBroadcastChannel.channels = []
  }

  name: string
  onmessage: ((ev: { data: unknown }) => void) | null = null
  closed = false

  constructor(name: string) {
    this.name = name
    MockBroadcastChannel.channels.push(this)
  }

  postMessage(data: unknown) {
    const clone = structuredClone(data)
    for (const ch of MockBroadcastChannel.channels) {
      if (ch !== this && ch.name === this.name && !ch.closed && ch.onmessage) {
        ch.onmessage({ data: clone })
      }
    }
  }

  close() {
    this.closed = true
  }
}

type BroadcastModule = typeof import('./broadcast')

/** Fresh module instance = a distinct "window" (own windowId + own state). */
async function loadWindow(): Promise<BroadcastModule> {
  vi.resetModules()
  return import('./broadcast')
}

function fakeClient() {
  const spy = vi.fn((...args: unknown[]) => {
    void args
    return Promise.resolve()
  })
  // Only the shape initBroadcastSync touches is needed.
  const client = { invalidateQueries: spy } as unknown as import('@tanstack/react-query').QueryClient
  return { client, spy }
}

const originalBC = globalThis.BroadcastChannel

beforeEach(() => {
  MockBroadcastChannel.reset()
  // @ts-expect-error override with the in-process double
  globalThis.BroadcastChannel = MockBroadcastChannel
})

afterEach(() => {
  globalThis.BroadcastChannel = originalBC
  MockBroadcastChannel.reset()
})

describe('broadcast sync bus', () => {
  it('mirrors a local invalidation to peer windows', async () => {
    const winA = await loadWindow()
    const winB = await loadWindow()
    const a = fakeClient()
    const b = fakeClient()
    winA.initBroadcastSync(a.client)
    winB.initBroadcastSync(b.client)

    a.client.invalidateQueries({ queryKey: ['notebooks', 'x'] })

    // Local invalidation still runs.
    expect(a.spy.mock.calls[0][0]).toEqual({ queryKey: ['notebooks', 'x'] })
    // Peer applied the same key exactly once — no echo loop back to A.
    expect(b.spy).toHaveBeenCalledTimes(1)
    expect(b.spy.mock.calls[0][0]).toEqual({ queryKey: ['notebooks', 'x'] })
  })

  it('applies a remote invalidation without re-broadcasting (no loop)', async () => {
    const winA = await loadWindow()
    const winB = await loadWindow()
    const a = fakeClient()
    const b = fakeClient()
    winA.initBroadcastSync(a.client)
    winB.initBroadcastSync(b.client)

    a.client.invalidateQueries({ queryKey: ['notes', 'n1'] })

    // A invalidated once (local); B invalidated once (mirror). If B had
    // re-broadcast, A would have been called a second time.
    expect(a.spy).toHaveBeenCalledTimes(1)
    expect(b.spy).toHaveBeenCalledTimes(1)
  })

  it('does not broadcast excluded query-key families', async () => {
    const winA = await loadWindow()
    const winB = await loadWindow()
    const a = fakeClient()
    const b = fakeClient()
    winA.initBroadcastSync(a.client)
    winB.initBroadcastSync(b.client)

    a.client.invalidateQueries({ queryKey: ['commands', 'active'] })

    // Local still runs, peer is untouched.
    expect(a.spy).toHaveBeenCalledTimes(1)
    expect(b.spy).not.toHaveBeenCalled()
  })

  it('does not broadcast invalidations without a query key', async () => {
    const winA = await loadWindow()
    const winB = await loadWindow()
    const a = fakeClient()
    const b = fakeClient()
    winA.initBroadcastSync(a.client)
    winB.initBroadcastSync(b.client)

    a.client.invalidateQueries()

    expect(a.spy).toHaveBeenCalledTimes(1)
    expect(b.spy).not.toHaveBeenCalled()
  })

  it('resolves an intent when a peer acks it', async () => {
    const winA = await loadWindow()
    const winB = await loadWindow()

    const handler = vi.fn(() => true)
    const unsub = winB.onIntent('ask-ai', handler)

    const acked = await winA.sendIntent('ask-ai', { text: 'hi' }, { timeoutMs: 500 })

    expect(acked).toBe(true)
    expect(handler).toHaveBeenCalledWith({ text: 'hi' })
    unsub()
  })

  it('resolves false when no peer acks within the timeout', async () => {
    const winA = await loadWindow()
    await loadWindow() // a silent peer with no handler

    const acked = await winA.sendIntent('ask-ai', { text: 'hi' }, { timeoutMs: 20 })
    expect(acked).toBe(false)
  })

  it('resolves false when a peer declines (handler returns false)', async () => {
    const winA = await loadWindow()
    const winB = await loadWindow()
    winB.onIntent('ask-ai', () => false)

    const acked = await winA.sendIntent('ask-ai', {}, { timeoutMs: 20 })
    expect(acked).toBe(false)
  })

  it('stops delivering to an unsubscribed intent handler', async () => {
    const winA = await loadWindow()
    const winB = await loadWindow()
    const handler = vi.fn(() => true)
    const unsub = winB.onIntent('ask-ai', handler)
    unsub()

    const acked = await winA.sendIntent('ask-ai', {}, { timeoutMs: 20 })
    expect(acked).toBe(false)
    expect(handler).not.toHaveBeenCalled()
  })

  it('exports the excluded key prefixes and intent-type constants', async () => {
    const win = await loadWindow()
    expect(win.EXCLUDED_KEY_PREFIXES).toContainEqual(['commands', 'active'])
    expect(win.INTENT_ASK_AI).toBe('ask-ai')
    expect(win.INTENT_ANNOTATION_JUMP).toBe('annotation-jump')
  })

  it('no-ops when BroadcastChannel is unavailable (SSR / capability guard)', async () => {
    // @ts-expect-error simulate missing capability
    delete globalThis.BroadcastChannel
    const win = await loadWindow()
    const { client, spy } = fakeClient()

    // init must not throw and must not replace invalidateQueries.
    win.initBroadcastSync(client)
    client.invalidateQueries({ queryKey: ['notebooks'] })
    expect(spy).toHaveBeenCalledTimes(1)

    // intent API degrades gracefully.
    await expect(win.sendIntent('ask-ai', {})).resolves.toBe(false)
    expect(win.onIntent('ask-ai', () => true)).toBeTypeOf('function')
  })
})
