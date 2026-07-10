'use client'

import { useState, useRef, useCallback, useEffect, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Bot, FileText, Lightbulb, StickyNote, Clock } from 'lucide-react'
import {
  SourceChatMessage,
  SourceChatContextIndicator,
  BaseChatSession,
  MediaItem
} from '@/lib/types/api'
import { ModelSelector } from './ModelSelector'
import { ContextIndicator } from '@/components/common/ContextIndicator'
import { SessionManager } from './SessionManager'
import { useModalManager } from '@/lib/hooks/use-modal-manager'
import { toast } from 'sonner'
import { useTranslation } from '@/lib/hooks/use-translation'
import { MessageList } from './MessageList'
import { ChatComposer } from './ChatComposer'

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
  // Live phase (+ tool name/input) for the in-flight job, if any (Track: live
  // tool-call progress). Undefined for chat kinds without a tool loop (source
  // chat) or before the model has reported anything yet.
  activeProgress?: { phase?: string; tool_name?: string; tool_input?: Record<string, unknown> }
  contextIndicators: SourceChatContextIndicator | null
  onSendMessage: (message: string, modelOverride?: string, media?: MediaItem[]) => void | Promise<{ ok: boolean } | void>
  modelOverride?: string
  onModelChange?: (model?: string) => void
  sessions?: BaseChatSession[]
  currentSessionId?: string | null
  onCreateSession?: (title: string) => void
  onSelectSession?: (sessionId: string) => void
  onDeleteSession?: (sessionId: string) => void
  onUpdateSession?: (sessionId: string, title: string) => void
  loadingSessions?: boolean
  title?: string
  contextType?: 'source' | 'notebook'
  notebookContextStats?: NotebookContextStats
  notebookId?: string
  variant?: 'standalone' | 'dock'
  draft?: string
  onDraftChange?: (value: string) => void
  composerMaxHeight?: number
  composerHeader?: ReactNode
  composerToolbar?: ReactNode
  emptyStateTitle?: string
  emptyStateHelper?: string
  suggestions?: string[]
  chatScopeId?: string
  // D8: source-chat only — forwarded to MessageList so annotation reference pills
  // render and route their jump to the active PDF/Reader tab.
  sourceId?: string
  autoFocus?: boolean
  /**
   * Bump to focus the composer and drop the caret at the end of the draft.
   * Used when "Ask AI" stages a prompt instead of sending it, so the user can
   * keep typing. A counter rather than a boolean: staging the same prompt twice
   * must still re-focus.
   */
  focusSignal?: number
  pending?: MediaItem[]
  onAddPending?: (item: MediaItem) => void
  onRemovePending?: (index: number) => void
  onRetry?: (messageId: string) => void
}

export function ChatPanel({
  messages,
  isStreaming,
  activeProgress,
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
  sourceId,
  autoFocus = false,
  focusSignal,
  pending,
  onAddPending,
  onRemovePending,
  onRetry,
}: ChatPanelProps) {
  const { t } = useTranslation()
  const [internalInput, setInternalInput] = useState('')
  const [sessionManagerOpen, setSessionManagerOpen] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { openModal } = useModalManager()

  const isDock = variant === 'dock'
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

  // `openModal` and `t` are re-created each render — keep the latest in a ref and
  // expose a fully stable `handleReferenceClick` so memoized AIMessageContent
  // can skip re-rendering prior messages on each new turn.
  const refClickDeps = useRef({ openModal, t })
  refClickDeps.current = { openModal, t }

  // Phase3 forwards an optional cited page (`[source:id#p=N]`) as a 3rd arg.
  // Decision #20: a page-level source citation opens the source modal straight to
  // the inline PDF at that page; non-page citations keep the C4 behavior (scroll
  // to the notebook source card or the chaptered section anchor).
  const handleReferenceClick = useCallback((type: string, id: string, page?: number) => {
    const { openModal, t } = refClickDeps.current
    // Decision #20: an explicit "show me page N" → open the inline PDF at it.
    if (type === 'source' && page != null) {
      try {
        openModal('source', id, page)
      } catch {
        toast.error(t('common.noResults'))
      }
      return
    }
    if (type === 'source' && typeof document !== 'undefined') {
      const sel = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(id) : id
      // 1. Notebook sources-list card (existing behavior).
      const card = document.querySelector<HTMLElement>(`[data-source-id="${sel}"]`)
      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        card.classList.remove('source-flash')
        void card.offsetWidth
        card.classList.add('source-flash')
        window.setTimeout(() => card.classList.remove('source-flash'), 1700)
        return
      }
      // 2. Chaptered source detail (C4): if the citation id matches a rendered
      //    chapter anchor, scroll to that section instead of opening a modal.
      const sectionEl = document.querySelector<HTMLElement>(`[data-section-id="${sel}"]`)
      if (sectionEl) {
        sectionEl.scrollIntoView({ behavior: 'smooth', block: 'start' })
        return
      }
    }

    const modalType = type === 'source_insight' ? 'insight' : type as 'source' | 'note' | 'insight'

    try {
      openModal(modalType, id)
    } catch {
      toast.error(t('common.noResults'))
    }
  }, [])

  // Focus the composer when a caller stages a draft into it. Runs after the new
  // value has been committed to the textarea, so `value.length` is the end of
  // the staged prompt rather than of whatever it replaced.
  useEffect(() => {
    if (!focusSignal) return
    const el = textareaRef.current
    if (!el) return
    el.focus()
    el.setSelectionRange(el.value.length, el.value.length)
  }, [focusSignal])

  // Send is allowed with text OR ≥1 pending attachment.
  const canSend = (inputValue.trim().length > 0 || pendingMedia.length > 0) && !isStreaming

  const handleSend = async () => {
    if (!canSend) return
    const text = inputValue.trim()
    const media = pendingMedia.length ? pendingMedia : undefined
    setInputValue('')
    const outcome = await onSendMessage(text, modelOverride, media)
    if (outcome && outcome.ok === false) {
      // Send failed: restore draft and re-focus so the user can retry.
      setInputValue(text)
      requestAnimationFrame(() => textareaRef.current?.focus())
    }
  }

  const handleSuggestion = (prompt: string) => {
    if (isStreaming) return
    onSendMessage(prompt, modelOverride)
    setInputValue('')
  }

  const messageList = (
    <MessageList
      messages={messages}
      isStreaming={isStreaming}
      activeProgress={activeProgress}
      isDock={isDock}
      emptyStateTitle={emptyStateTitle}
      emptyStateHelper={emptyStateHelper}
      suggestions={suggestions}
      contextType={contextType}
      chatScopeId={chatScopeId}
      notebookId={notebookId}
      sourceId={sourceId}
      onReferenceClick={handleReferenceClick}
      onSuggestion={handleSuggestion}
      onRetry={onRetry}
    />
  )

  const composer = (
    <ChatComposer
      inputValue={inputValue}
      onInputChange={setInputValue}
      onSend={handleSend}
      isStreaming={isStreaming}
      canSend={canSend}
      isDock={isDock}
      mediaEnabled={mediaEnabled}
      pendingMedia={pendingMedia}
      onRemovePending={onRemovePending}
      onAddPending={onAddPending}
      composerHeader={composerHeader}
      composerToolbar={composerToolbar}
      composerMaxHeight={composerMaxHeight}
      autoFocus={autoFocus}
      textareaRef={textareaRef}
    />
  )

  if (isDock) {
    return (
      <div className="flex flex-col h-full min-h-0">
        {messageList}
        {composer}
      </div>
    )
  }

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
        {messageList}

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

        {notebookContextStats && (
          <ContextIndicator
            sourcesInsights={notebookContextStats.sourcesInsights}
            sourcesFull={notebookContextStats.sourcesFull}
            notesCount={notebookContextStats.notesCount}
            tokenCount={notebookContextStats.tokenCount}
            charCount={notebookContextStats.charCount}
          />
        )}

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
