/**
 * Cross-window sync bus (BroadcastChannel).
 *
 * A single `BroadcastChannel('open-notebook-sync')` lets independent browser
 * windows/tabs of the app stay in step:
 *
 *  1. **Query-invalidation mirroring** — when one window invalidates a React
 *     Query key (a mutation landed, a chat job finished, …), the same
 *     invalidation is re-broadcast and re-applied by peer windows so their UI
 *     refreshes near-instantly instead of waiting on the 10s jobs poller.
 *     Wired via `initBroadcastSync(queryClient)`, a guarded monkey-patch of the
 *     singleton `queryClient.invalidateQueries` (Decisions #5 / P-bus-emitter).
 *     Deliberately NO MutationCache — per-hook onError toasts are load-bearing.
 *
 *  2. **Intent / ack plumbing** — `sendIntent`/`onIntent` give a generic
 *     request→ack round-trip so one window can hand an action (ask-AI a passage,
 *     jump to an annotation) to whichever peer window can service it. Consumed
 *     by Track C's C4.
 *
 * SSR / capability safety: every export no-ops when there is no `window` or no
 * `BroadcastChannel`. The API-feel (init once, no-op if absent) mirrors
 * `annotation-jump-store`.
 */

import type { QueryClient } from '@tanstack/react-query'

export const CHANNEL_NAME = 'open-notebook-sync'

/** Envelope version — bump on breaking payload changes so peers can ignore. */
const PROTOCOL_VERSION = 1

/**
 * Query-key families that must NOT be broadcast-mirrored.
 * - `['commands','active']`: the jobs poller's own key. EVERY window already
 *   polls it independently, so mirroring it would be pure echo noise (and could
 *   feed an invalidation storm as each window's poll re-triggers the others).
 * Extend this list (see Q-bc-exclusions) if another family proves chatty/loopy.
 */
export const EXCLUDED_KEY_PREFIXES: readonly (readonly unknown[])[] = [
  ['commands', 'active'],
]

/** Intent type constants (payload shapes documented where C4 consumes them). */
export const INTENT_ASK_AI = 'ask-ai'
export const INTENT_ANNOTATION_JUMP = 'annotation-jump'

type MessageType = 'invalidate' | 'intent' | 'ack'

interface InvalidatePayload {
  queryKey: unknown[]
}
interface IntentPayload {
  intentType: string
  requestId: string
  data: unknown
}
interface AckPayload {
  requestId: string
}

interface Envelope {
  v: number
  from: string
  type: MessageType
  payload: InvalidatePayload | IntentPayload | AckPayload
}

export type IntentHandler = (data: unknown) => boolean | Promise<boolean>

// ---------------------------------------------------------------------------
// Module state (one instance per window; in tests, per fresh module import).
// ---------------------------------------------------------------------------

function isSupported(): boolean {
  return typeof window !== 'undefined' && 'BroadcastChannel' in window
}

/** Stable per-window id so a window can recognise (and drop) its own echoes. */
const windowId: string =
  isSupported() && typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : ''

// `undefined` = not yet attempted; `null` = unsupported; otherwise the channel.
let channel: BroadcastChannel | null | undefined
let initialized = false

/**
 * Re-entrancy guard: true while we are applying a *remote* invalidation, so the
 * patched `invalidateQueries` does not re-broadcast it and loop forever.
 */
let applyingRemote = false

/** Applies a mirrored invalidation locally. Set by `initBroadcastSync`. */
let applyRemoteInvalidate: ((queryKey: unknown[]) => void) | null = null

const intentHandlers = new Map<string, Set<IntentHandler>>()
const ackWaiters = new Map<string, (acked: boolean) => void>()

function newId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function getChannel(): BroadcastChannel | null {
  if (!isSupported()) return null
  if (channel === undefined) {
    channel = new BroadcastChannel(CHANNEL_NAME)
    channel.onmessage = onChannelMessage
  }
  return channel
}

function post(envelope: Envelope): void {
  const ch = getChannel()
  ch?.postMessage(envelope)
}

// ---------------------------------------------------------------------------
// Receive path
// ---------------------------------------------------------------------------

function onChannelMessage(event: MessageEvent): void {
  const msg = event.data as Envelope | undefined
  if (!msg || msg.v !== PROTOCOL_VERSION) return
  // BroadcastChannel never echoes to the poster, but guard defensively.
  if (msg.from && msg.from === windowId) return

  switch (msg.type) {
    case 'invalidate': {
      const { queryKey } = msg.payload as InvalidatePayload
      if (applyRemoteInvalidate && Array.isArray(queryKey)) {
        applyingRemote = true
        try {
          applyRemoteInvalidate(queryKey)
        } finally {
          applyingRemote = false
        }
      }
      break
    }
    case 'intent':
      void handleIncomingIntent(msg.payload as IntentPayload)
      break
    case 'ack': {
      const { requestId } = msg.payload as AckPayload
      ackWaiters.get(requestId)?.(true)
      break
    }
  }
}

async function handleIncomingIntent(payload: IntentPayload): Promise<void> {
  const { intentType, requestId, data } = payload
  const handlers = intentHandlers.get(intentType)
  if (!handlers || handlers.size === 0) return
  for (const handler of handlers) {
    let acked = false
    try {
      acked = await handler(data)
    } catch {
      acked = false
    }
    if (acked) {
      post({ v: PROTOCOL_VERSION, from: windowId, type: 'ack', payload: { requestId } })
      return // first-acker wins
    }
  }
}

// ---------------------------------------------------------------------------
// Emitter: patch queryClient.invalidateQueries (Decisions #5 / P-bus-emitter)
// ---------------------------------------------------------------------------

function isExcluded(queryKey: unknown[]): boolean {
  return EXCLUDED_KEY_PREFIXES.some(
    (prefix) =>
      queryKey.length >= prefix.length &&
      prefix.every((part, i) => Object.is(queryKey[i], part))
  )
}

/**
 * Wrap the singleton `queryClient.invalidateQueries` so every *local*
 * invalidation is mirrored to peer windows. Idempotent; no-op under SSR / no
 * BroadcastChannel. Called once from the query-client module (runs per window).
 */
export function initBroadcastSync(queryClient: QueryClient): void {
  if (!isSupported() || initialized) return
  initialized = true

  const originalInvalidate = queryClient.invalidateQueries.bind(queryClient)

  // Applying a remote invalidation goes through the ORIGINAL (never the patched
  // fn), so it cannot re-broadcast — the flag is belt-and-suspenders.
  applyRemoteInvalidate = (queryKey: unknown[]) => {
    void originalInvalidate({ queryKey })
  }

  queryClient.invalidateQueries = ((filters?: unknown, options?: unknown) => {
    const result = (originalInvalidate as (f?: unknown, o?: unknown) => Promise<void>)(
      filters,
      options
    )
    const queryKey = (filters as { queryKey?: unknown[] } | undefined)?.queryKey
    if (
      !applyingRemote &&
      Array.isArray(queryKey) &&
      !isExcluded(queryKey)
    ) {
      post({
        v: PROTOCOL_VERSION,
        from: windowId,
        type: 'invalidate',
        payload: { queryKey },
      })
    }
    return result
  }) as typeof queryClient.invalidateQueries

  // Ensure the channel exists so this window also receives peer invalidations.
  getChannel()
}

// ---------------------------------------------------------------------------
// Intent / ack API (consumed by C4)
// ---------------------------------------------------------------------------

/**
 * Broadcast an intent and wait for any peer to ack it.
 * Resolves `true` on the first matching ack within `timeoutMs` (default 300),
 * else `false`. Always resolves `false` under SSR / no BroadcastChannel.
 */
export function sendIntent(
  type: string,
  payload: unknown,
  opts?: { timeoutMs?: number }
): Promise<boolean> {
  const ch = getChannel()
  if (!ch) return Promise.resolve(false)

  const requestId = newId()
  const timeoutMs = opts?.timeoutMs ?? 300

  return new Promise<boolean>((resolve) => {
    let settled = false
    const finish = (acked: boolean) => {
      if (settled) return
      settled = true
      ackWaiters.delete(requestId)
      clearTimeout(timer)
      resolve(acked)
    }
    const timer = setTimeout(() => finish(false), timeoutMs)
    ackWaiters.set(requestId, () => finish(true))
    ch.postMessage({
      v: PROTOCOL_VERSION,
      from: windowId,
      type: 'intent',
      payload: { intentType: type, requestId, data: payload },
    } satisfies Envelope)
  })
}

/**
 * Register a handler for an intent type. The handler returns `true` to ack
 * (claim the intent). Returns an unsubscribe fn. No-op (returns a no-op
 * unsubscribe) under SSR / no BroadcastChannel.
 */
export function onIntent(intentType: string, handler: IntentHandler): () => void {
  if (!isSupported()) return () => {}
  getChannel() // ensure channel + receive wiring exist

  let set = intentHandlers.get(intentType)
  if (!set) {
    set = new Set()
    intentHandlers.set(intentType, set)
  }
  set.add(handler)

  return () => {
    const current = intentHandlers.get(intentType)
    if (!current) return
    current.delete(handler)
    if (current.size === 0) intentHandlers.delete(intentType)
  }
}
