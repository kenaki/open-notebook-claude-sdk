'use client'

import { useRouter, useParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ArrowLeft, MessageSquare, Quote, X } from 'lucide-react'
import { useSourceChat } from '@/lib/hooks/useSourceChat'
import { ChatPanel } from '@/components/source/chat'
import { useNavigation } from '@/lib/hooks/use-navigation'
import { SourceDetailContent } from '@/components/source/detail'
import { useTranslation } from '@/lib/hooks/use-translation'

// Remembers whether the chat column was open across visits/reloads.
const CHAT_OPEN_KEY = 'source-detail-chat-open'

// Cap on annotation ids sent with one tag-ask (Q-tag-ask-limit / agent context).
const MAX_TAG_ANNOTATION_IDS = 10

// FALLBACK ONLY (D8): quote-paste for highlights that carry no annotation id
// (a fresh, un-saved selection). The primary path now sends structured
// `annotation_ids` and a short localized user text. Hardcoded English, matching
// the single-highlight prompt below (neither is localized).
function composeTagPrompt(tag: string, quotes: string[]): string {
  if (quotes.length === 0) {
    return `Tell me about my highlights tagged "${tag}".`
  }
  const list = quotes.map((quote, i) => `${i + 1}. "${quote}"`).join('\n')
  return `Here are my highlights tagged "${tag}":\n${list}\n\nHelp me understand these together.`
}

export default function SourceDetailPage() {
  const router = useRouter()
  const params = useParams()
  const { t } = useTranslation()
  const sourceId = params?.id ? decodeURIComponent(params.id as string) : ''
  const navigation = useNavigation()

  // Initialize source chat
  const chat = useSourceChat(sourceId)

  // Collapsible chat column: closed by default so the document (esp. the PDF)
  // gets the full width. Hidden via CSS rather than unmounted so a typed draft
  // or in-flight stream survives toggling.
  const [chatOpen, setChatOpen] = useState(false)
  useEffect(() => {
    try {
      setChatOpen(window.localStorage.getItem(CHAT_OPEN_KEY) === '1')
    } catch {
      // localStorage unavailable (private mode) — keep the default.
    }
  }, [])
  const toggleChat = useCallback(() => {
    setChatOpen((prev) => {
      const next = !prev
      try {
        window.localStorage.setItem(CHAT_OPEN_KEY, next ? '1' : '0')
      } catch {
        // Non-persistent toggle is still fine.
      }
      return next
    })
  }, [])

  // "Ask AI" stages a prompt into the composer rather than sending it, so the
  // user can edit it first and choose to send it into a fresh chat. `askRefs`
  // are the structured annotation ids that ride along with the staged draft;
  // they attach to whatever the user finally sends, and only clear on a
  // successful send (a failed one restores the draft, so the refs must survive).
  const [draft, setDraft] = useState('')
  const [askRefs, setAskRefs] = useState<string[] | null>(null)
  const [focusSignal, setFocusSignal] = useState(0)

  const stageAsk = useCallback((text: string, annotationIds: string[]) => {
    setChatOpen(true)
    setDraft(text)
    setAskRefs(annotationIds)
    setFocusSignal((n) => n + 1)
  }, [])

  const handleBack = useCallback(() => {
    const returnPath = navigation.getReturnPath()
    router.push(returnPath)
    navigation.clearReturnTo()
  }, [navigation, router])

  // Shown above the composer while an Ask-AI prompt is staged: what's attached,
  // an escape hatch, and the option to route this question into a new chat.
  const composerHeader = askRefs ? (
    <div className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2 py-1.5">
      <Quote className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
        {askRefs.length > 0
          ? t('chat.askDraft.attached').replace('{count}', String(askRefs.length))
          : t('chat.askDraft.attachedQuote')}
      </span>
      {chat.pendingNewSession ? (
        <span className="flex-shrink-0 text-xs font-medium text-primary">
          {t('chat.askDraft.newChatReady')}
        </span>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          className="h-6 flex-shrink-0 px-2 text-xs"
          onClick={chat.startNewSession}
        >
          {t('chat.askDraft.newChat')}
        </Button>
      )}
      <button
        type="button"
        onClick={() => setAskRefs(null)}
        aria-label={t('chat.askDraft.dismiss')}
        className="flex-shrink-0 rounded p-0.5 text-muted-foreground hover:bg-background"
      >
        <X className="h-3 w-3" aria-hidden="true" />
      </button>
    </div>
  ) : undefined

  const chatLabel = t('chat.chatWith').replace('{name}', t('navigation.sources'))

  return (
    <div className="flex h-screen">
      {/* Document area: single-line toolbar (back · title · tabs · actions ·
          chat toggle) + the active tab filling the rest of the viewport. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <SourceDetailContent
          sourceId={sourceId}
          layout="toolbar"
          toolbarLeading={
            <Button
              variant="ghost"
              size="sm"
              onClick={handleBack}
              className="flex-shrink-0"
            >
              <ArrowLeft className="mr-2 h-4 w-4" />
              {navigation.getReturnLabel()}
            </Button>
          }
          toolbarTrailing={
            <Button
              variant={chatOpen ? 'secondary' : 'outline'}
              size="sm"
              onClick={toggleChat}
              title={chatLabel}
              aria-label={chatLabel}
              aria-pressed={chatOpen}
            >
              <MessageSquare className="h-4 w-4" />
            </Button>
          }
          showChatButton={false}
          onClose={handleBack}
          onChatAboutHighlight={(quote, annotationId) => {
            // D8: an existing highlight → structured annotation ref + short text;
            // a fresh un-saved selection (no id) → quote-paste fallback.
            if (annotationId) {
              stageAsk(t('chat.askAboutHighlight'), [annotationId])
            } else {
              stageAsk(`Tell me about this highlighted passage: "${quote}"`, [])
            }
          }}
          onChatAboutHighlights={(quotes, tag, annotationIds) => {
            const ids = annotationIds ?? []
            if (ids.length > 0) {
              const capped = ids.slice(0, MAX_TAG_ANNOTATION_IDS)
              if (ids.length > MAX_TAG_ANNOTATION_IDS) {
                toast.info(t('chat.tagAskTruncated').replace('{tag}', tag))
              }
              stageAsk(t('chat.askAboutTag').replace('{tag}', tag), capped)
            } else {
              stageAsk(composeTagPrompt(tag, quotes), [])
            }
          }}
        />
      </div>

      {/* Chat column: fixed width so the document keeps the remaining space. */}
      <div
        className={
          chatOpen
            ? 'flex w-[400px] flex-shrink-0 flex-col border-l border-border p-3 xl:w-[440px]'
            : 'hidden'
        }
      >
        <ChatPanel
          sourceId={sourceId}
          messages={chat.messages}
          isStreaming={chat.isStreaming}
          // X-viewprocess-sourcechat (agent-console B4): source chat's job rows
          // carry `sessionId` = the source-chat session id (registered in
          // useSourceChat's sendMessage), matching notebook chat's ChatDock/
          // PoppedChatPanel convention of forwarding the active session id as
          // `chatScopeId` so MessageList's pending-bubble "view process" button
          // can find this session's in-flight job.
          chatScopeId={chat.currentSessionId ?? undefined}
          contextIndicators={chat.contextIndicators}
          draft={draft}
          onDraftChange={setDraft}
          focusSignal={focusSignal}
          composerHeader={composerHeader}
          // Attach any staged annotation refs to whatever the user actually
          // sends — they may have edited the prompt first. Cleared only on
          // success; ChatPanel restores the draft on failure, so the refs must
          // still be there for the retry.
          onSendMessage={async (message, model) => {
            const ids = askRefs
            const outcome = await chat.sendMessage(
              message,
              model,
              ids?.length ? { annotationIds: ids } : undefined
            )
            if (outcome.ok) setAskRefs(null)
            return outcome
          }}
          modelOverride={chat.currentSession?.model_override}
          onModelChange={(model) => {
            if (chat.currentSessionId) {
              chat.updateSession(chat.currentSessionId, { model_override: model })
            }
          }}
          sessions={chat.sessions}
          currentSessionId={chat.currentSessionId}
          onCreateSession={(title) => chat.createSession({ title })}
          onSelectSession={chat.switchSession}
          onUpdateSession={(sessionId, title) => chat.updateSession(sessionId, { title })}
          onDeleteSession={chat.deleteSession}
          loadingSessions={chat.loadingSessions}
        />
      </div>
    </div>
  )
}
