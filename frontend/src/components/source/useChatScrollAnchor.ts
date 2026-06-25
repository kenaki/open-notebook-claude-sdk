import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import type { SourceChatMessage } from '@/lib/types/api'

// Manages smooth-scroll behaviour in the dock chat:
// - new human turn  → pin the prompt to the top of the viewport (scroll + spacer).
// - AI reply        → let it grow below; re-pin if optimistic→real id swap shifts the anchor.
// - tab switch / history load → jump to bottom, reset spacer.
// - standalone source chat  → simple scroll-to-bottom (isDock=false path).
export function useChatScrollAnchor({
  isDock,
  messages,
  scrollAreaRef,
  messagesEndRef,
}: {
  isDock: boolean
  messages: SourceChatMessage[]
  scrollAreaRef: RefObject<HTMLDivElement | null>
  messagesEndRef: RefObject<HTMLDivElement | null>
}) {
  const [tailSpacer, setTailSpacer] = useState(0)
  const prevCountRef = useRef(0)
  const pinActiveRef = useRef(false)
  // Mirror of `tailSpacer` readable synchronously inside pinPrompt's timed
  // callbacks so the spacer can be recomputed from the *natural* content height.
  const tailSpacerRef = useRef(0)

  const setSpacer = (height: number) => {
    tailSpacerRef.current = height
    setTailSpacer(height)
  }

  const pinPrompt = (messageId: string) => {
    const run = () => {
      const viewport = scrollAreaRef.current?.querySelector<HTMLElement>(
        '[data-slot="scroll-area-viewport"]'
      )
      if (!viewport) return
      const sel = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(messageId) : messageId
      const el = viewport.querySelector<HTMLElement>(`[data-msg-id="${sel}"]`)
      // Stale timer (e.g. the optimistic temp id was swapped for the real one on
      // reconcile): the element is gone, so leave the spacer/scroll to the
      // re-pin that the reconcile fires for the new id.
      if (!el) return
      // Size the spacer to exactly the room the prompt needs to reach the top.
      // Subtract the current spacer back out to measure the natural content height.
      const naturalHeight = viewport.scrollHeight - tailSpacerRef.current
      const belowPrompt = naturalHeight - el.offsetTop
      setSpacer(Math.max(0, viewport.clientHeight - belowPrompt))
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
    run()
    ;[60, 180, 360].forEach((d) => window.setTimeout(run, d))
  }

  useEffect(() => {
    const prev = prevCountRef.current
    prevCountRef.current = messages.length
    const last = messages[messages.length - 1]
    const grew = messages.length > prev
    const isNewHumanTurn = grew && last?.type === 'human'

    if (!isDock) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      return
    }

    if (isNewHumanTurn && last) {
      pinActiveRef.current = true
      pinPrompt(last.id)
    } else if (grew && pinActiveRef.current) {
      // The pinned turn's reply landed. Re-pin the latest human message by its
      // *current* id (reconcile may have swapped the temp id for the real one).
      pinActiveRef.current = false
      let lastHuman: SourceChatMessage | undefined
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].type === 'human') { lastHuman = messages[i]; break }
      }
      if (lastHuman) pinPrompt(lastHuman.id)
      else setSpacer(0)
    } else {
      pinActiveRef.current = false
      setSpacer(0)
      messagesEndRef.current?.scrollIntoView({ behavior: 'auto' })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages])

  return { tailSpacer }
}
