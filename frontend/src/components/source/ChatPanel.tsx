'use client'

import { useState, useRef, useEffect, useId } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Bot, Send, Loader2, FileText, Lightbulb, StickyNote, Clock, Sparkles, Image as ImageIcon, Video as VideoIcon, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
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
import { MessageReferences, FollowupChips } from '@/components/source/MessageReferences'
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
  onSendMessage: (message: string, modelOverride?: string, media?: MediaItem[]) => void
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

  const handleReferenceClick = (type: string, id: string) => {
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
  }

  // Smooth-scroll the just-sent prompt near the top ("new-turn feel"). Re-runs on
  // a few timers to survive reflow / tab-backgrounding (per the handoff pinPrompt).
  const pinPrompt = (messageId: string) => {
    const run = () => {
      const viewport = scrollAreaRef.current?.querySelector<HTMLElement>(
        '[data-slot="scroll-area-viewport"]'
      )
      if (!viewport) return
      const sel = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(messageId) : messageId
      const el = viewport.querySelector<HTMLElement>(`[data-msg-id="${sel}"]`)
      if (!el) return
      // Grow the spacer so a short answer can still scroll the prompt to the top.
      setTailSpacer(viewport.clientHeight)
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
      // AI reply for the pinned turn — keep the prompt at the top.
    } else {
      pinActiveRef.current = false
      setTailSpacer(0)
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

  const handleSend = () => {
    if (canSend) {
      onSendMessage(inputValue.trim(), modelOverride, pendingMedia.length ? pendingMedia : undefined)
      setInputValue('')
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
          messages.map((message) => {
            const isHuman = message.type === 'human'
            return (
              <div
                key={message.id}
                data-msg-id={message.id}
                style={{ scrollMarginTop: 8 }}
                className={`flex ${isHuman ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`flex flex-col gap-1.5 max-w-[82%] ${isHuman ? 'items-end' : 'items-start'}`}
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
                    className={`px-3.5 py-2.5 ${isHuman ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground'}`}
                    style={{ borderRadius: isHuman ? USER_BUBBLE_RADIUS : AI_BUBBLE_RADIUS }}
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
                  {message.type === 'ai' && message.followups && message.followups.length > 0 && (
                    <FollowupChips
                      followups={message.followups}
                      onSelect={handleSuggestion}
                      disabled={isStreaming}
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
              <Loader2 className="h-4 w-4 animate-spin" />
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
    <div className="flex-shrink-0 p-4 space-y-2 border-t">
      {/* Staged attachments (Plan D / Chunk 12): monospace filename + remove ✕. */}
      {mediaEnabled && pendingMedia.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
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
      <div className="flex gap-2 items-end min-w-0">
        {mediaEnabled && (
          <div className="flex items-center gap-0.5 flex-shrink-0">
            <input ref={imageInputRef} type="file" accept="image/*" className="hidden" onChange={handleAttach} />
            <input ref={videoInputRef} type="file" accept="video/*" className="hidden" onChange={handleAttach} />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-[40px] w-[34px] text-text-3"
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
              className="h-[40px] w-[34px] text-text-3"
              title={t('chat.attachVideo')}
              disabled={isStreaming || uploading}
              onClick={() => videoInputRef.current?.click()}
            >
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <VideoIcon className="h-4 w-4" />}
            </Button>
          </div>
        )}
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
          className="flex-1 min-h-[40px] resize-none overflow-y-auto py-2 px-3 min-w-0"
          style={{ maxHeight }}
          rows={1}
        />
        <Button
          onClick={handleSend}
          disabled={!canSend}
          size="icon"
          className="h-[40px] w-[40px] flex-shrink-0"
        >
          {isStreaming ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </Button>
      </div>
      {isDock && (
        <p className="text-[11px] text-text-3">
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

// Helper component to render AI messages with clickable references
function AIMessageContent({
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
  const markdownWithCompactRefs = convertReferencesToCompactMarkdown(content, t('common.references'), appendReferenceList)

  // Create custom link component for compact references
  const LinkComponent = createCompactReferenceLinkComponent(onReferenceClick)

  return (
    <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none break-words prose-headings:font-semibold prose-a:text-blue-600 prose-a:break-all prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-p:mb-4 prose-p:leading-7 prose-li:mb-2">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a: LinkComponent,
          p: ({ children }) => <p className="mb-4">{children}</p>,
          h1: ({ children }) => <h1 className="mb-4 mt-6">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-3 mt-5">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-3 mt-4">{children}</h3>,
          h4: ({ children }) => <h4 className="mb-2 mt-4">{children}</h4>,
          h5: ({ children }) => <h5 className="mb-2 mt-3">{children}</h5>,
          h6: ({ children }) => <h6 className="mb-2 mt-3">{children}</h6>,
          li: ({ children }) => <li className="mb-1">{children}</li>,
          ul: ({ children }) => <ul className="mb-4 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="mb-4 space-y-1">{children}</ol>,
          table: ({ children }) => (
            <div className="my-4 overflow-x-auto">
              <table className="min-w-full border-collapse border border-border">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-b border-border">{children}</tr>,
          th: ({ children }) => <th className="border border-border px-3 py-2 text-left font-semibold">{children}</th>,
          td: ({ children }) => <td className="border border-border px-3 py-2">{children}</td>,
        }}
      >
        {markdownWithCompactRefs}
      </ReactMarkdown>
    </div>
  )
}
