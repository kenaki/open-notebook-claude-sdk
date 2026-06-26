'use client'

import { memo, useMemo, useRef } from 'react'
import { Sparkles } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import { MarkdownCodeBlock } from './MarkdownCodeBlock'
import { MessageActions } from './MessageActions'
import { MessageReferences } from './MessageReferences'
import { MessageMedia } from './MessageMedia'
import { ToolUseDisclosure } from './ToolUseDisclosure'
import { convertReferencesToCompactMarkdown, createCompactReferenceLinkComponent } from '@/lib/utils/source-references'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { SourceChatMessage } from '@/lib/types/api'
import { useChatScrollAnchor } from './useChatScrollAnchor'

// Bubble radii: sender-side corner near the tail is sharp (4px), the other three 14px.
const USER_BUBBLE_RADIUS = '14px 14px 4px 14px'
const AI_BUBBLE_RADIUS = '14px 14px 14px 4px'

// Stable inline-style object for the per-message scroll anchor — hoisted so the
// message .map doesn't allocate a fresh object per row each render.
const MSG_SCROLL_MARGIN = { scrollMarginTop: 8 }

interface MessageListProps {
  messages: SourceChatMessage[]
  isStreaming: boolean
  isDock: boolean
  emptyStateTitle?: string
  emptyStateHelper?: string
  suggestions?: string[]
  contextType?: 'source' | 'notebook'
  chatScopeId?: string
  notebookId?: string
  onReferenceClick: (type: string, id: string) => void
  onSuggestion: (prompt: string) => void
  onRetry?: (messageId: string) => void
}

export function MessageList({
  messages,
  isStreaming,
  isDock,
  emptyStateTitle,
  emptyStateHelper,
  suggestions,
  contextType = 'source',
  chatScopeId,
  notebookId,
  onReferenceClick,
  onSuggestion,
  onRetry,
}: MessageListProps) {
  const { t } = useTranslation()
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { tailSpacer } = useChatScrollAnchor({ isDock, messages, scrollAreaRef, messagesEndRef })

  const fallbackEmptyTitle = emptyStateTitle
    ?? t('chat.startConversation').replace('{type}', contextType === 'source' ? t('navigation.sources') : t('common.notebook'))
  const fallbackEmptyHelper = emptyStateHelper ?? t('chat.askQuestions')

  return (
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
                    onClick={() => onSuggestion(prompt)}
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
            const showDivider = isHuman && index > 0

            // Pending placeholder: spinner bubble while the worker generates.
            if (message.pending) {
              return (
                <div
                  key={message.id}
                  data-msg-id={message.id}
                  style={MSG_SCROLL_MARGIN}
                  className="flex justify-start"
                >
                  <div
                    className="px-3.5 py-2.5 bg-muted text-foreground"
                    style={{ borderRadius: AI_BUBBLE_RADIUS }}
                  >
                    <LoadingSpinner size="sm" />
                    <span className="sr-only">{t('chat.generating')}</span>
                  </div>
                </div>
              )
            }

            // Error placeholder: failure bubble with optional retry affordance.
            if (message.error) {
              return (
                <div
                  key={message.id}
                  data-msg-id={message.id}
                  style={MSG_SCROLL_MARGIN}
                  className="flex justify-start"
                >
                  <div className="flex flex-col gap-1.5 items-start">
                    <div
                      className="px-3.5 py-2.5 text-sm text-destructive bg-destructive/10"
                      style={{ borderRadius: AI_BUBBLE_RADIUS }}
                    >
                      {t('chat.generationFailed')}
                    </div>
                    {onRetry && (
                      <button
                        type="button"
                        onClick={() => onRetry(message.id)}
                        className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2 transition-colors"
                      >
                        {t('chat.retry')}
                      </button>
                    )}
                  </div>
                </div>
              )
            }

            return (
              <div
                key={message.id}
                data-msg-id={message.id}
                style={MSG_SCROLL_MARGIN}
                className={`flex ${isHuman ? 'justify-end' : 'justify-start'} ${showDivider ? 'chat-turn-divider' : ''}`}
              >
                <div
                  className={`flex flex-col gap-1.5 ${isHuman ? 'max-w-[82%] items-end' : 'w-full items-start'}`}
                  data-chat-scope={!isHuman ? chatScopeId : undefined}
                >
                  {isHuman && message.media && message.media.length > 0 && (
                    <MessageMedia media={message.media} className="justify-end" />
                  )}
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
                        onReferenceClick={onReferenceClick}
                        appendReferenceList={!message.citations?.length}
                      />
                    )}
                  </div>
                  {message.type === 'ai' && message.media && message.media.length > 0 && (
                    <MessageMedia media={message.media} className="mt-[12px]" />
                  )}
                  {message.type === 'ai' && message.citations && message.citations.length > 0 && (
                    <MessageReferences
                      citations={message.citations}
                      onReferenceClick={onReferenceClick}
                    />
                  )}
                  {message.type === 'ai' && (
                    <MessageActions content={message.content} notebookId={notebookId} />
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
}

// Renders AI message markdown with clickable references. Memoized so a new turn
// doesn't re-parse every prior message — only re-renders when content/handler change.
// The parent passes a stable `onReferenceClick` (useCallback) so the memo holds.
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
  const markdownWithCompactRefs = useMemo(
    () => convertReferencesToCompactMarkdown(content, t('common.references'), appendReferenceList),
    [content, appendReferenceList, t]
  )
  const LinkComponent = useMemo(
    () => createCompactReferenceLinkComponent(onReferenceClick),
    [onReferenceClick]
  )

  return (
    <div className="chat-markdown prose prose-sm prose-neutral dark:prose-invert max-w-none break-words prose-headings:font-semibold prose-a:break-all">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeHighlight, rehypeKatex]}
        components={{
          a: LinkComponent,
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
