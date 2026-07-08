'use client'

import { useRouter, useParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { ArrowLeft, MessageSquare } from 'lucide-react'
import { useSourceChat } from '@/lib/hooks/useSourceChat'
import { ChatPanel } from '@/components/source/chat'
import { useNavigation } from '@/lib/hooks/use-navigation'
import { SourceDetailContent } from '@/components/source/detail'
import { useTranslation } from '@/lib/hooks/use-translation'

// Remembers whether the chat column was open across visits/reloads.
const CHAT_OPEN_KEY = 'source-detail-chat-open'

// Builds the batch "ask AI about all highlights tagged X" chat message.
// Hardcoded English, matching the single-highlight prompt below (neither is
// localized). Empty quotes are already filtered out by the caller.
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

  const handleBack = useCallback(() => {
    const returnPath = navigation.getReturnPath()
    router.push(returnPath)
    navigation.clearReturnTo()
  }, [navigation, router])

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
          onChatAboutHighlight={(quote) => {
            setChatOpen(true)
            chat.sendMessage(`Tell me about this highlighted passage: "${quote}"`)
          }}
          onChatAboutHighlights={(quotes, tag) => {
            setChatOpen(true)
            chat.sendMessage(composeTagPrompt(tag, quotes))
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
          messages={chat.messages}
          isStreaming={chat.isStreaming}
          contextIndicators={chat.contextIndicators}
          onSendMessage={(message, model) => chat.sendMessage(message, model)}
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
