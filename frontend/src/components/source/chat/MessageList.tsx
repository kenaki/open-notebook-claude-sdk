'use client'

import { memo, useCallback, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { Activity, Sparkles } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import { MarkdownCodeBlock } from './MarkdownCodeBlock'
import { MessageActions } from './MessageActions'
import { MessageReferences, AnnotationReferences } from './MessageReferences'
import { RecallReferences } from './RecallReferences'
import { MessageMedia } from './MessageMedia'
import { useAnnotationJumpStore } from '@/lib/stores/annotation-jump-store'
import { ToolUseDisclosure, describeTool, detailFor } from './ToolUseDisclosure'
import { ThinkingDisclosure } from './ThinkingDisclosure'
import { convertReferencesToCompactMarkdown, createCompactReferenceLinkComponent } from '@/lib/utils/source-references'
import { navigateToRecallRef } from '@/lib/utils/recall-navigation'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { RecallRef, SourceChatMessage } from '@/lib/types/api'
import { useChatScrollAnchor } from './useChatScrollAnchor'
import { useJobsStore, type BackgroundJob } from '@/lib/stores/jobs-store'
import { useAgentConsoleStore } from '@/lib/stores/agent-console-store'

// Bubble radii: sender-side corner near the tail is sharp (4px), the other three 14px.
const USER_BUBBLE_RADIUS = '14px 14px 4px 14px'
const AI_BUBBLE_RADIUS = '14px 14px 14px 4px'

// Stable inline-style object for the per-message scroll anchor — hoisted so the
// message .map doesn't allocate a fresh object per row each render.
const MSG_SCROLL_MARGIN = { scrollMarginTop: 8 }

interface MessageListProps {
  messages: SourceChatMessage[]
  isStreaming: boolean
  // Live phase (+ tool name/input) for the in-flight job, if any. Undefined
  // for chat kinds without a tool loop, or before anything's been reported.
  activeProgress?: { phase?: string; tool_name?: string; tool_input?: Record<string, unknown> }
  isDock: boolean
  emptyStateTitle?: string
  emptyStateHelper?: string
  suggestions?: string[]
  contextType?: 'source' | 'notebook'
  chatScopeId?: string
  notebookId?: string
  // D8: source-chat surfaces always pass this; it enables annotation reference
  // pills on human turns and routes their "jump to highlight" click to the
  // active PDF/Reader tab. Notebook chat omits it — its refs carry their own
  // per-ref `source_id` instead (cross-interface-study Track B3), since a
  // notebook spans multiple sources.
  sourceId?: string
  onReferenceClick: (type: string, id: string) => void
  onSuggestion: (prompt: string) => void
  onRetry?: (messageId: string) => void
  // study-memory C2: switches THIS chat surface to another of its OWN sessions
  // in place (source chat's `useSourceChat().switchSession`). Only relevant to
  // a recall pill pointing at a same-source exchange; absent in notebook chat,
  // where every recall pill navigates via router instead (see
  // `navigateToRecallRef`).
  onSwitchSession?: (sessionId: string) => void
}

export function MessageList({
  messages,
  isStreaming,
  activeProgress,
  isDock,
  emptyStateTitle,
  emptyStateHelper,
  suggestions,
  contextType = 'source',
  chatScopeId,
  notebookId,
  sourceId,
  onReferenceClick,
  onSuggestion,
  onRetry,
  onSwitchSession,
}: MessageListProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const requestJump = useAnnotationJumpStore((s) => s.requestJump)
  // study-memory C2: resolves a recall-pill click per the branch table in
  // `navigateToRecallRef` — session-level navigation only (coordinator
  // P-nav-depth), never a message-level scroll. Built here (not threaded down
  // as a ready-made callback) because MessageList already owns everything the
  // branch table needs except `onSwitchSession`, which is the one piece only
  // the source-chat page can supply.
  const handleOpenRecallRef = useCallback(
    (ref: RecallRef) =>
      navigateToRecallRef(ref, {
        sourceId,
        switchSession: onSwitchSession,
        requestJump,
        push: router.push,
      }),
    [sourceId, onSwitchSession, requestJump, router]
  )
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { tailSpacer } = useChatScrollAnchor({ isDock, messages, scrollAreaRef, messagesEndRef })
  // agent-console B3: `chatScopeId` doubles as the active session id here (see
  // ChatDock/PoppedChatPanel, which pass `activeMainId`/`session.id`) — used to
  // find this session's in-flight job so the pending bubble can offer a
  // "view process" shortcut into the console. Undefined chatScopeId (source
  // chat's ChatPanel doesn't forward one today) simply means no button shows.
  const activeSessionJob = useJobsStore((s) =>
    chatScopeId
      ? s.jobs.find((j) => j.sessionId === chatScopeId && (j.status === 'new' || j.status === 'running'))
      : undefined
  )
  // All jobs, so a `pending-<jobId>` placeholder can find its own job by id and
  // render the streamed answer-so-far (progress.partial_content). Works for both
  // source and notebook chat regardless of whether chatScopeId is forwarded.
  const storeJobs = useJobsStore((s) => s.jobs)

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

            // Pending placeholder: while the worker generates, render the
            // answer-so-far streamed onto the job (progress.partial_content) with
            // the spinner beneath, or a bare spinner bubble before any text lands.
            if (message.pending) {
              const jobId = message.id.startsWith('pending-')
                ? message.id.slice('pending-'.length)
                : null
              const streamingJob = jobId
                ? storeJobs.find((job) => job.jobId === jobId)
                : undefined
              const partial = streamingJob?.progress?.partial_content
              return (
                <div
                  key={message.id}
                  data-msg-id={message.id}
                  style={MSG_SCROLL_MARGIN}
                  className="flex justify-start"
                >
                  {partial && partial.trim() ? (
                    <div className="flex w-full flex-col items-start gap-1.5">
                      <div className="w-full text-foreground chat-msg-enter">
                        <AIMessageContent
                          content={partial}
                          onReferenceClick={onReferenceClick}
                          appendReferenceList={false}
                        />
                      </div>
                      <PendingBubble
                        activeProgress={activeProgress}
                        activeJob={activeSessionJob ?? streamingJob}
                      />
                    </div>
                  ) : (
                    <PendingBubble
                      activeProgress={activeProgress}
                      activeJob={activeSessionJob ?? streamingJob}
                    />
                  )}
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
                  {message.type === 'ai' && message.thinking && (
                    <ThinkingDisclosure thinking={message.thinking} />
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
                  {isHuman && message.annotation_refs && message.annotation_refs.length > 0 &&
                    (sourceId || message.annotation_refs.some((ref) => ref.source_id)) && (
                    <AnnotationReferences
                      refs={message.annotation_refs}
                      sourceId={sourceId}
                      onJumpTo={(ref) => {
                        // cross-interface-study Track B3: a notebook-chat ref can
                        // point at a different source than the surface's own
                        // sourceId (source chat always has one; notebook chat
                        // never does) — prefer the ref's own source_id.
                        const targetSourceId = ref.source_id ?? sourceId
                        if (targetSourceId) requestJump(targetSourceId, ref.id)
                      }}
                    />
                  )}
                  {message.type === 'ai' && message.media && message.media.length > 0 && (
                    <MessageMedia media={message.media} className="mt-[12px]" />
                  )}
                  {message.type === 'ai' && message.citations && message.citations.length > 0 && (
                    <MessageReferences
                      citations={message.citations}
                      onReferenceClick={onReferenceClick}
                    />
                  )}
                  {message.type === 'ai' && message.recall_refs && message.recall_refs.length > 0 && (
                    <RecallReferences refs={message.recall_refs} onOpenRef={handleOpenRecallRef} />
                  )}
                  {message.type === 'ai' && (
                    <MessageActions content={message.content} notebookId={notebookId} />
                  )}
                </div>
              </div>
            )
          })
        )}
        {/* Only for the brief pre-registration round-trip: once the job is
            registered, sendMessageTo/useSourceChat insert a `pending` placeholder
            message (rendered above) that owns the spinner for the rest of the
            job's lifetime — showing both would double up. */}
        {isStreaming && !messages.some((message) => message.pending) && (
          <div className="flex justify-start">
            <PendingBubble activeProgress={activeProgress} activeJob={activeSessionJob} />
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

// Shared "generating…" bubble: the spinner + live progress label, plus (B3) a
// ghost "view process" button that opens the agent console straight onto this
// session's in-flight job. Used both by the persisted `pending` placeholder
// message and the brief pre-registration fallback bubble below it.
function PendingBubble({
  activeProgress,
  activeJob,
}: {
  activeProgress?: { phase?: string; tool_name?: string; tool_input?: Record<string, unknown> }
  activeJob?: BackgroundJob
}) {
  const { t } = useTranslation()
  return (
    <div
      className="flex items-center gap-2 px-3.5 py-2.5 bg-muted text-foreground"
      style={{ borderRadius: AI_BUBBLE_RADIUS }}
    >
      <LoadingSpinner size="sm" />
      <LiveProgressLabel activeProgress={activeProgress} />
      {activeJob && (
        <button
          type="button"
          onClick={() => useAgentConsoleStore.getState().open(activeJob.jobId)}
          className="ml-1 flex flex-shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <Activity className="h-3 w-3" aria-hidden="true" />
          {t('chat.viewProcess')}
        </button>
      )}
    </div>
  )
}

// Live label next to the generating spinner. When the backend has reported a
// tool call in progress (see open_notebook.graphs.chat's tool loop), shows
// the same localized, icon-matched label as the post-hoc ToolUseDisclosure
// but in present-continuous tense ("Searching…" not "Searched…") — otherwise
// falls back to the generic "Generating…" copy.
function LiveProgressLabel({
  activeProgress,
}: {
  activeProgress?: { phase?: string; tool_name?: string; tool_input?: Record<string, unknown> }
}) {
  const { t } = useTranslation()
  if (activeProgress?.tool_name) {
    const { liveKey, Icon } = describeTool(activeProgress.tool_name)
    const detail = activeProgress.tool_input ? detailFor(activeProgress.tool_input) : null
    return (
      <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
        <span className="flex-shrink-0">{t(liveKey)}</span>
        {detail && <span className="truncate font-mono text-text-3">{detail}</span>}
      </span>
    )
  }
  return <span className="text-xs text-muted-foreground">{t('chat.generating')}</span>
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
