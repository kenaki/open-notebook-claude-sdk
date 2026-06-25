'use client'

import { useState, useRef, useEffect, useId, useCallback, useMemo, memo, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Bot, Send, FileText, Lightbulb, StickyNote, Clock, Sparkles, Image as ImageIcon, Video as VideoIcon, X } from 'lucide-react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import { MarkdownCodeBlock } from '@/components/source/MarkdownCodeBlock'
import {
  SourceChatMessage,
  SourceChatContextIndicator,
  BaseChatSession,
  MediaItem
} from '@/lib/types/api'
import { ModelSelector } from './ModelSelector'
import { ContextIndicator } from '@/components/common/ContextIndicator'
import { SessionManager } from '@/components/source/SessionManager'
import { MessageActions } from '@/components/source/MessageActions'
import { convertReferencesToCompactMarkdown, createCompactReferenceLinkComponent } from '@/lib/utils/source-references'
import { MessageReferences } from '@/components/source/MessageReferences'
import { ToolUseDisclosure } from '@/components/source/ToolUseDisclosure'
import { MessageMedia } from '@/components/source/MessageMedia'
import { chatApi } from '@/lib/api/chat'
import { useModalManager } from '@/lib/hooks/use-modal-manager'
import { toast } from 'sonner'
import { useTranslation } from '@/lib/hooks/use-translation'

// Bubble radii from the handoff: the sender-side corner near the tail is sharp
// (4px), the other three are 14px. AI bubbles mirror the user bubble.
const USER_BUBBLE_RADIUS = '14px 14px 4px 14px'
const AI_BUBBLE_RADIUS = '14px 14px 14px 4px'

// Stable inline-style object for the per-message scroll anchor — hoisted so the
// message `.map` doesn't allocate a fresh object per row each render (A3).
const MSG_SCROLL_MARGIN = { scrollMarginTop: 8 }

interface NotebookContextStats {
  sourcesInsights: number
  sourcesFull: number
  notesCount: number
  tokenCount?: number
  charCount?: number
}

interface ChatPanelProps {
  messages: SourceChatMessage[]
  isStreaming: boolean
  contextIndicators: SourceChatContextIndicator | null
  // Returning `{ ok: false }` (the notebook dock path) tells the composer the send
  // failed so it can restore the user's draft (Track A / A2). Handlers that don't
  // signal (source chat) return void and the composer keeps its clear-on-send
  // behavior.
  onSendMessage: (message: string, modelOverride?: string, media?: MediaItem[]) => void | Promise<{ ok: boolean } | void>
  modelOverride?: string
  onModelChange?: (model?: string) => void
  // Session management props
  sessions?: BaseChatSession[]
  currentSessionId?: string | null
  onCreateSession?: (title: string) => void
  onSelectSession?: (sessionId: string) => void
  onDeleteSession?: (sessionId: string) => void
  onUpdateSession?: (sessionId: string, title: string) => void
  loadingSessions?: boolean
  // Generic props for reusability
  title?: string
  contextType?: 'source' | 'notebook'
  // Notebook context stats (for notebook chat)
  notebookContextStats?: NotebookContextStats
  // Notebook ID for saving notes
  notebookId?: string
  // --- Multi-chat dock (Plan C / Chunk 7) ---
  // 'dock' drops the standalone card chrome (header, model selector, context
  // indicators) — the Chat Dock renders those itself — and shows the dock
  // composer hint. 'standalone' keeps the source-chat surface unchanged.
  variant?: 'standalone' | 'dock'
  // Controlled composer text (per-chat draft). When omitted the panel keeps its
  // own internal input state (source chat).
  draft?: string
  onDraftChange?: (value: string) => void
  // Composer auto-grow cap in px (140 dock / 100 standalone default).
  composerMaxHeight?: number
  // Slot rendered above the input box (the dock feeds its tabs here so they sit
  // over the textbox, leaving the conversation the full height of the card).
  composerHeader?: ReactNode
  // Slot rendered in the utility toolbar row *inside* the input box, below the
  // textarea and left of the send button. Panel controls live here — the dock's
  // model picker + context meter + settings cog, a popped panel's model picker —
  // so they're cleanly separated from the typing area.
  composerToolbar?: ReactNode
  // Empty-state copy + preset suggestion prompts (clicking sends immediately).
  emptyStateTitle?: string
  emptyStateHelper?: string
  suggestions?: string[]
  // Sub-chats (Plan D / Chunk 11): when set, each AI message body is tagged with
  // `data-chat-scope={chatScopeId}` so a passage selection can be traced back to
  // the chat it came from (the prospective parent). Omitted on source chat.
  chatScopeId?: string
  // Focus the composer on mount (used when a freshly-spawned sub-chat appears).
  autoFocus?: boolean
  // Media attachments (Plan D / Chunk 12). Only wired on the dock variant (dock +
  // popped panels); source chat leaves these undefined so its composer is
  // unchanged. `pending` are already-uploaded items staged in the composer; the
  // ghost buttons upload via POST /chat/media and call `onAddPending`.
  pending?: MediaItem[]
  onAddPending?: (item: MediaItem) => void
  onRemovePending?: (index: number) => void
}

export function ChatPanel({
  messages,
  isStreaming,
  contextIndicators,
  onSendMessage,
  modelOverride,
  onModelChange,
  sessions = [],
  currentSessionId,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
  onUpdateSession,
  loadingSessions = false,
  title,
  contextType = 'source',
  notebookContextStats,
  notebookId,
  variant = 'standalone',
  draft,
  onDraftChange,
  composerMaxHeight,
  composerHeader,
  composerToolbar,
  emptyStateTitle,
  emptyStateHelper,
  suggestions,
  chatScopeId,
  autoFocus = false,
  pending,
  onAddPending,
  onRemovePending,
}: ChatPanelProps) {
  const { t } = useTranslation()
  const chatInputId = useId()
  const [internalInput, setInternalInput] = useState('')
  const [sessionManagerOpen, setSessionManagerOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const videoInputRef = useRef<HTMLInputElement>(null)
  // Prompt-pin (handoff §"Composer behavior"): tail spacer grown on send so the
  // just-sent prompt can reach the top, plus refs tracking the turn count and
  // whether a pin is currently active (so the AI reply doesn't un-pin it).
  const [tailSpacer, setTailSpacer] = useState(0)
  const prevCountRef = useRef(0)
  const pinActiveRef = useRef(false)
  // Mirror of `tailSpacer` readable synchronously inside pinPrompt's timed
  // callbacks so the spacer can be recomputed from the *natural* content height
  // (scrollHeight minus the spacer it currently contributes).
  const tailSpacerRef = useRef(0)
  const { openModal } = useModalManager()

  const isDock = variant === 'dock'
  const maxHeight = composerMaxHeight ?? (isDock ? 140 : 100)
  // Media attachments only on the dock variant, and only when the parent wired
  // the staging callbacks (dock + popped chats — not source chat).
  const mediaEnabled = isDock && !!onAddPending
  const pendingMedia = pending ?? []

  // Controlled (dock per-chat draft) vs. uncontrolled (source chat) composer.
  const isControlled = draft !== undefined && !!onDraftChange
  const inputValue = isControlled ? draft! : internalInput
  const setInputValue = (value: string) => {
    if (isControlled) {
      onDraftChange!(value)
    } else {
      setInternalInput(value)
    }
  }

  // `openModal` (URL-param based) and `t` are re-created each render, so keep the
  // latest in a ref and expose a fully stable `handleReferenceClick`. A stable
  // identity is what lets the memoized `AIMessageContent` skip re-rendering prior
  // messages on each new turn (A3).
  const refClickDeps = useRef({ openModal, t })
  refClickDeps.current = { openModal, t }

  const handleReferenceClick = useCallback((type: string, id: string) => {
    const { openModal, t } = refClickDeps.current
    // Citation → flash the matching source card in the Sources panel (handoff
    // §"Citations": accent ring, 1.7s). `id` arrives bare (MessageReferences
    // strips the "source:" prefix) and SourceCard stamps the same bare id on
    // data-source-id. If the card isn't currently mounted (panel collapsed,
    // source off-page, or this is the standalone source chat) we fall back to
    // the existing modal so the citation still resolves.
    if (type === 'source' && typeof document !== 'undefined') {
      const sel = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(id) : id
      const card = document.querySelector<HTMLElement>(`[data-source-id="${sel}"]`)
      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        // Restart the animation if the same citation is clicked again.
        card.classList.remove('source-flash')
        void card.offsetWidth
        card.classList.add('source-flash')
        window.setTimeout(() => card.classList.remove('source-flash'), 1700)
        return
      }
    }

    const modalType = type === 'source_insight' ? 'insight' : type as 'source' | 'note' | 'insight'

    try {
      openModal(modalType, id)
      // Note: The modal system uses URL parameters and doesn't throw errors for missing items.
      // The modal component itself will handle displaying "not found" states.
      // This try-catch is here for future enhancements or unexpected errors.
    } catch {
      toast.error(t('common.noResults'))
    }
  }, [])

  // Smooth-scroll the just-sent prompt near the top ("new-turn feel"). Re-runs on
  // a few timers to survive reflow / tab-backgrounding (per the handoff pinPrompt).
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
      // Size the spacer to *exactly* the room the prompt needs to reach the top:
      // viewport height minus whatever real content already sits below the
      // prompt. `scrollHeight` includes the current spacer, so subtract it back
      // out to measure the natural content. This keeps a short answer scrollable
      // to the top without leaving a viewport-tall blank gap under a long one.
      const naturalHeight = viewport.scrollHeight - tailSpacerRef.current
      const belowPrompt = naturalHeight - el.offsetTop
      setSpacer(Math.max(0, viewport.clientHeight - belowPrompt))
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
    run()
    ;[60, 180, 360].forEach((d) => window.setTimeout(run, d))
  }

  // Scroll behavior on message changes:
  // - Dock/popped, new user turn  → pin the prompt to the top.
  // - Dock/popped, AI reply for a pinned turn → leave it pinned (answer grows below).
  // - Dock/popped, tab switch / history load → jump to the latest, reset the spacer.
  // - Standalone source chat → keep the simple scroll-to-bottom.
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
      // The pinned turn's reply landed. This is also where the optimistic→server
      // reconcile swaps the human turn's temp id for its real one, so re-pin the
      // latest human message by its *current* id — otherwise the anchor (the now
      // removed temp element) is lost and the view drifts past the prompt into
      // the tail spacer. Release the pin afterwards so later history/session
      // loads scroll normally rather than re-pinning an unrelated turn.
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

  // Focus the composer on mount when requested (a freshly-spawned sub-chat).
  // Mount-only so re-renders don't steal focus mid-typing.
  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Auto-grow the composer up to the cap, then scroll. Re-runs on draft changes
  // (incl. switching dock tabs) so a restored draft sizes correctly.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
  }, [inputValue, maxHeight])

  // Send is allowed with text OR ≥1 pending attachment (handoff §"Composer").
  const canSend = (inputValue.trim().length > 0 || pendingMedia.length > 0) && !isStreaming

  const handleSend = async () => {
    if (!canSend) return
    // Capture the draft (+ staged media) before the optimistic clear so a failed
    // send can restore it instead of silently losing the user's text (Track A / A2).
    const text = inputValue.trim()
    const media = pendingMedia.length ? pendingMedia : undefined
    setInputValue('')
    const outcome = await onSendMessage(text, modelOverride, media)
    if (outcome && outcome.ok === false) {
      // Send failed (the optimistic bubble was rolled back + a toast shown). Put
      // the draft back and re-focus so the user can retry without retyping; the
      // dock keeps the staged media (it only clears pending on success).
      setInputValue(text)
      requestAnimationFrame(() => textareaRef.current?.focus())
    }
  }

  // Upload a picked file via POST /chat/media, then stage the returned MediaItem.
  const handleAttach = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-picking the same file
    if (!file || !onAddPending) return
    setUploading(true)
    try {
      const item = await chatApi.uploadMedia(file)
      onAddPending(item)
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }; message?: string }
      toast.error(error.response?.data?.detail || error.message || t('chat.uploadFailed'))
    } finally {
      setUploading(false)
    }
  }

  const handleSuggestion = (prompt: string) => {
    if (isStreaming) return
    onSendMessage(prompt, modelOverride)
    setInputValue('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Detect platform for correct modifier key
    const isMac = typeof navigator !== 'undefined' && navigator.userAgent.toUpperCase().indexOf('MAC') >= 0
    const isModifierPressed = isMac ? e.metaKey : e.ctrlKey

    if (e.key === 'Enter' && isModifierPressed) {
      e.preventDefault()
      handleSend()
    }
  }

  // Detect platform for placeholder text
  const isMac = typeof navigator !== 'undefined' && navigator.userAgent.toUpperCase().indexOf('MAC') >= 0
  const keyHint = isMac ? '⌘+Enter' : 'Ctrl+Enter'

  const fallbackEmptyTitle = emptyStateTitle
    ?? t('chat.startConversation').replace('{type}', contextType === 'source' ? t('navigation.sources') : t('common.notebook'))
  const fallbackEmptyHelper = emptyStateHelper ?? t('chat.askQuestions')

  // Shared conversation area (messages + empty state), reused by both variants.
  const conversation = (
    <ScrollArea className="flex-1 min-h-0 px-4" ref={scrollAreaRef}>
      <div className="space-y-4 py-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center text-center py-10 px-4">
            <div className="h-11 w-11 rounded-full bg-accent-soft flex items-center justify-center mb-3">
              <Sparkles className="h-5 w-5 text-primary" />
            </div>
            <p className="text-sm font-medium text-foreground">{fallbackEmptyTitle}</p>
            <p className="text-xs text-muted-foreground mt-1 max-w-[280px]">{fallbackEmptyHelper}</p>
            {suggestions && suggestions.length > 0 && (
              <div className="flex flex-col gap-2 mt-5 w-full max-w-[320px]">
                {suggestions.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => handleSuggestion(prompt)}
                    disabled={isStreaming}
                    className="text-left text-xs rounded-lg border border-border bg-card hover:bg-accent px-3 py-2 text-foreground transition-colors disabled:opacity-50"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          messages.map((message, index) => {
            const isHuman = message.type === 'human'
            // Hairline between Q&A pairs: a new human turn (after the first message)
            // gets a faint divider above it so each exchange reads as its own block.
            const showDivider = isHuman && index > 0
            return (
              <div
                key={message.id}
                data-msg-id={message.id}
                style={MSG_SCROLL_MARGIN}
                className={`flex ${isHuman ? 'justify-end' : 'justify-start'} ${showDivider ? 'chat-turn-divider' : ''}`}
              >
                <div
                  // Human turns stay a right-aligned bubble (capped width); AI
                  // turns render full-width as a document — no bubble, no wasted
                  // right margin (Claude/ChatGPT convention).
                  className={`flex flex-col gap-1.5 ${isHuman ? 'max-w-[82%] items-end' : 'w-full items-start'}`}
                  // Tag AI bodies with the originating chat id so a passage
                  // selection resolves its parent (Chunk 11); human turns aren't
                  // selectable into sub-chats.
                  data-chat-scope={!isHuman ? chatScopeId : undefined}
                >
                  {/* User media: tiles right-aligned above the bubble (Plan D /
                      Chunk 12). */}
                  {isHuman && message.media && message.media.length > 0 && (
                    <MessageMedia media={message.media} className="justify-end" />
                  )}
                  {/* Tool-use disclosure renders above the answer text (Plan D /
                      Chunk 10). Null/absent on the Esperanto path → nothing. */}
                  {message.type === 'ai' && message.tool_uses && message.tool_uses.length > 0 && (
                    <ToolUseDisclosure toolUses={message.tool_uses} />
                  )}
                  <div
                    className={
                      isHuman
                        ? 'px-3.5 py-2.5 bg-primary-soft text-primary-foreground'
                        : 'w-full text-foreground chat-msg-enter'
                    }
                    style={isHuman ? { borderRadius: USER_BUBBLE_RADIUS } : undefined}
                  >
                    {isHuman ? (
                      <p className="text-sm whitespace-pre-wrap break-words">{message.content}</p>
                    ) : (
                      <AIMessageContent
                        content={message.content}
                        onReferenceClick={handleReferenceClick}
                        // When structured citation cards render below, suppress the
                        // appended markdown reference list to avoid duplication.
                        appendReferenceList={!message.citations?.length}
                      />
                    )}
                  </div>
                  {/* AI media: tiles below the answer text (Plan D / Chunk 12). */}
                  {message.type === 'ai' && message.media && message.media.length > 0 && (
                    <MessageMedia media={message.media} className="mt-[12px]" />
                  )}
                  {/* Structured citations + follow-up chips (Plan D / Chunk 9). */}
                  {message.type === 'ai' && message.citations && message.citations.length > 0 && (
                    <MessageReferences
                      citations={message.citations}
                      onReferenceClick={handleReferenceClick}
                    />
                  )}
                  {message.type === 'ai' && (
                    <MessageActions
                      content={message.content}
                      notebookId={notebookId}
                    />
                  )}
                </div>
              </div>
            )
          })
        )}
        {isStreaming && (
          <div className="flex justify-start">
            <div
              className="px-3.5 py-2.5 bg-muted text-foreground"
              style={{ borderRadius: AI_BUBBLE_RADIUS }}
            >
              <LoadingSpinner size="sm" />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
        {/* Tail spacer (prompt-pin): grown on send so a short answer can still
            scroll the prompt to the top; reset on tab switch / history load. */}
        {tailSpacer > 0 && <div aria-hidden="true" style={{ height: tailSpacer }} />}
      </div>
    </ScrollArea>
  )

  // Shared composer.
  const composer = (
    <div className="flex-shrink-0 p-3 border-t">
      {/* Above the input box: dock tabs (composerHeader). */}
      {composerHeader && <div className="mb-2.5">{composerHeader}</div>}

      {/* The input box: an inset surface a touch lighter than the panel with a
          subtle border that eases into a soft purple glow on focus. Wraps the
          textarea + a utility toolbar so typing area and controls read as one
          clean unit. */}
      <div className="rounded-xl border border-border bg-composer transition-[border-color,box-shadow] duration-200 focus-within:border-primary-soft-border focus-within:ring-2 focus-within:ring-accent-soft">
        {/* Staged attachments (Plan D / Chunk 12): monospace filename + remove ✕. */}
        {mediaEnabled && pendingMedia.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-3 pt-3">
            {pendingMedia.map((item, index) => (
              <span
                key={`${item.url}-${index}`}
                className="inline-flex items-center gap-1 rounded-md bg-panel-2 border border-border pl-2 pr-1 py-1 text-[11px]"
              >
                {item.type === 'video' ? (
                  <VideoIcon className="h-3 w-3 text-text-3 flex-shrink-0" />
                ) : (
                  <ImageIcon className="h-3 w-3 text-text-3 flex-shrink-0" />
                )}
                <span className="font-mono truncate max-w-[140px] text-foreground">{item.label}</span>
                <button
                  type="button"
                  title={t('chat.removeAttachment')}
                  onClick={() => onRemovePending?.(index)}
                  className="p-0.5 rounded hover:bg-background text-text-3"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Roomy typing area — transparent (the box owns the surface/border), with
            generous vertical padding and a substantial min-height. */}
        <Textarea
          ref={textareaRef}
          id={chatInputId}
          name="chat-message"
          autoComplete="off"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isDock
            ? t('chat.sendPlaceholder')
            : `${t('chat.sendPlaceholder')} (${t('chat.pressToSend').replace('{key}', keyHint)})`}
          disabled={isStreaming}
          className="w-full min-h-[60px] resize-none overflow-y-auto border-0 bg-transparent dark:bg-transparent px-3.5 py-3.5 leading-relaxed shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
          style={{ maxHeight }}
          rows={1}
        />

        {/* Utility toolbar row: attach icons + panel controls on the left, send on
            the right — separated from the typing area above. */}
        <div className="flex items-center gap-1.5 px-2 pb-2 pt-0.5 min-w-0">
          {mediaEnabled && (
            <div className="flex items-center gap-0.5 flex-shrink-0">
              <input ref={imageInputRef} type="file" accept="image/*" className="hidden" onChange={handleAttach} />
              <input ref={videoInputRef} type="file" accept="video/*" className="hidden" onChange={handleAttach} />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-text-3"
                title={t('chat.attachImage')}
                disabled={isStreaming || uploading}
                onClick={() => imageInputRef.current?.click()}
              >
                <ImageIcon className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-text-3"
                title={t('chat.attachVideo')}
                disabled={isStreaming || uploading}
                onClick={() => videoInputRef.current?.click()}
              >
                {uploading ? <LoadingSpinner size="sm" /> : <VideoIcon className="h-4 w-4" />}
              </Button>
            </div>
          )}
          {composerToolbar && (
            <div className="flex items-center gap-1.5 min-w-0 overflow-hidden">
              {composerToolbar}
            </div>
          )}
          <div className="flex-1" />
          <Button
            onClick={handleSend}
            disabled={!canSend}
            size="icon"
            className="h-8 w-8 flex-shrink-0 rounded-lg bg-[var(--primary-soft)] hover:bg-[var(--primary-soft)]"
          >
            {isStreaming ? (
              <LoadingSpinner size="sm" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>

      {isDock && (
        <p className="mt-2.5 text-[11px] text-text-3">
          {t('chat.pressToSend').replace('{key}', keyHint)}
        </p>
      )}
    </div>
  )

  // Dock variant: bare body (no card chrome / header / model selector / context
  // indicators) — the Chat Dock supplies those. Card shell comes from the dock.
  if (isDock) {
    return (
      <div className="flex flex-col h-full min-h-0">
        {conversation}
        {composer}
      </div>
    )
  }

  // Standalone variant (source chat): unchanged card surface.
  return (
    <Card className="flex flex-col h-full flex-1 overflow-hidden">
      <CardHeader className="pb-3 flex-shrink-0">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5" />
            {title || (contextType === 'source' ? t('chat.chatWith').replace('{name}', t('navigation.sources')) : t('chat.chatWith').replace('{name}', t('common.notebook')))}
          </CardTitle>
          {onSelectSession && onCreateSession && onDeleteSession && (
            <Dialog open={sessionManagerOpen} onOpenChange={setSessionManagerOpen}>
              <Button
                variant="ghost"
                size="sm"
                className="gap-2"
                onClick={() => setSessionManagerOpen(true)}
                disabled={loadingSessions}
              >
                <Clock className="h-4 w-4" />
                <span className="text-xs">{t('chat.sessions')}</span>
              </Button>
              <DialogContent className="sm:max-w-[420px] p-0 overflow-hidden">
                <DialogTitle className="sr-only">{t('chat.sessionsTitle')}</DialogTitle>
                <SessionManager
                  sessions={sessions}
                  currentSessionId={currentSessionId ?? null}
                  onCreateSession={(title) => onCreateSession?.(title)}
                  onSelectSession={(sessionId) => {
                    onSelectSession(sessionId)
                    setSessionManagerOpen(false)
                  }}
                  onUpdateSession={(sessionId, title) => onUpdateSession?.(sessionId, title)}
                  onDeleteSession={(sessionId) => onDeleteSession?.(sessionId)}
                  loadingSessions={loadingSessions}
                />
              </DialogContent>
            </Dialog>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col min-h-0 p-0">
        {conversation}

        {/* Context Indicators */}
        {contextIndicators && (
          <div className="border-t px-4 py-2">
            <div className="flex flex-wrap gap-2 text-xs">
              {contextIndicators.sources?.length > 0 && (
                <Badge variant="outline" className="gap-1">
                  <FileText className="h-3 w-3" />
                  {contextIndicators.sources.length} {t('navigation.sources')}
                </Badge>
              )}
              {contextIndicators.insights?.length > 0 && (
                <Badge variant="outline" className="gap-1">
                  <Lightbulb className="h-3 w-3" />
                  {contextIndicators.insights.length} {contextIndicators.insights.length === 1 ? t('common.insight') : t('common.insights')}
                </Badge>
              )}
              {contextIndicators.notes?.length > 0 && (
                <Badge variant="outline" className="gap-1">
                  <StickyNote className="h-3 w-3" />
                  {contextIndicators.notes.length} {contextIndicators.notes.length === 1 ? t('common.note') : t('common.notes')}
                </Badge>
              )}
            </div>
          </div>
        )}

        {/* Notebook Context Indicator */}
        {notebookContextStats && (
          <ContextIndicator
            sourcesInsights={notebookContextStats.sourcesInsights}
            sourcesFull={notebookContextStats.sourcesFull}
            notesCount={notebookContextStats.notesCount}
            tokenCount={notebookContextStats.tokenCount}
            charCount={notebookContextStats.charCount}
          />
        )}

        {/* Model selector */}
        {onModelChange && (
          <div className="flex-shrink-0 px-4 pt-3 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">{t('chat.model')}</span>
            <ModelSelector
              currentModel={modelOverride}
              onModelChange={onModelChange}
              disabled={isStreaming}
              includeClaudeAgentSubmodels={contextType === 'notebook'}
            />
          </div>
        )}

        {composer}
      </CardContent>
    </Card>
  )
}

// Helper component to render AI messages with clickable references. Memoized so a
// new turn doesn't re-parse every prior message's markdown — it only re-renders
// when `content`/`onReferenceClick`/`appendReferenceList` change (A3). The parent
// passes a stable `onReferenceClick` (useCallback) so the memo holds across turns.
const AIMessageContent = memo(function AIMessageContent({
  content,
  onReferenceClick,
  appendReferenceList = true,
}: {
  content: string
  onReferenceClick: (type: string, id: string) => void
  appendReferenceList?: boolean
}) {
  const { t } = useTranslation()
  // Convert references to compact markdown with numbered citations. When
  // structured citation cards render the list separately, skip the appended one.
  // Memoized so the (non-trivial) reference conversion runs once per content.
  const markdownWithCompactRefs = useMemo(
    () => convertReferencesToCompactMarkdown(content, t('common.references'), appendReferenceList),
    [content, appendReferenceList, t]
  )

  // Create custom link component for compact references — stable per click handler
  // so ReactMarkdown's `components` prop doesn't churn each render.
  const LinkComponent = useMemo(
    () => createCompactReferenceLinkComponent(onReferenceClick),
    [onReferenceClick]
  )

  return (
    <div className="chat-markdown prose prose-sm prose-neutral dark:prose-invert max-w-none break-words prose-headings:font-semibold prose-a:break-all">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        // rehype-highlight tokenizes fenced code; rehype-katex renders math. They
        // touch disjoint nodes (code vs. math) so order is immaterial.
        rehypePlugins={[rehypeHighlight, rehypeKatex]}
        components={{
          a: LinkComponent,
          // Fenced code blocks get the header bar + copy button (MarkdownCodeBlock);
          // styling for the <pre>/<code> and everything else lives in `.chat-markdown`
          // (globals.css) so the renderer stays declarative.
          pre: MarkdownCodeBlock,
          table: ({ children }) => (
            <div className="chat-markdown-table">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {markdownWithCompactRefs}
      </ReactMarkdown>
    </div>
  )
})
