'use client'

import { ArrowLeftToLine, X, Quote } from 'lucide-react'
import { ChatPanel } from '@/components/source/ChatPanel'
import { ChatModelPicker } from '@/components/notebooks/ChatModelPicker'
import { DeleteChatButton } from '@/components/notebooks/DeleteChatButton'
import { deriveChatTitle } from '@/components/notebooks/ChatDock'
import { useChatWorkspaceStore } from '@/lib/stores/chat-workspace-store'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { BaseChatSession, MediaItem } from '@/lib/types/api'
import type { useNotebookChat } from '@/lib/hooks/useNotebookChat'

interface PoppedChatPanelProps {
  notebookId: string
  session: BaseChatSession
  // The single multiplexed chat hook (lifted to the page) — each popped panel
  // reads/sends to its own session id through it.
  chat: ReturnType<typeof useNotebookChat>
  onDockBack: () => void
  // X (non-destructive HIDE): stop rendering the panel; the chat stays in the
  // DB, reachable again via the sidebar / side-chats control (Chunk 3).
  onClose: () => void
  // Trash (permanent DELETE): remove the session (gated by a confirm dialog).
  onDelete: () => void
  // Focus this panel's composer on mount (a freshly-spawned sub-chat).
  autoFocus?: boolean
}

/**
 * A chat that has been popped out of the dock into its own side-by-side panel
 * (Plan C / Chunk 8). Reuses the {@link ChatPanel} dock body wired to the
 * multiplexed hook for this session, wrapped in a compact header (dock-back ⤵,
 * close ✕) and an optional "discussing this passage" banner for sub-chats
 * (`quote` is always null until Plan D adds sub-chats — the banner is built
 * here so they slot in for free).
 */
export function PoppedChatPanel({
  notebookId,
  session,
  chat,
  onDockBack,
  onClose,
  onDelete,
  autoFocus = false,
}: PoppedChatPanelProps) {
  const { t } = useTranslation()
  const workspaceChat = useChatWorkspaceStore((s) => s.chats[session.id])
  const setDraft = useChatWorkspaceStore((s) => s.setDraft)
  const addPending = useChatWorkspaceStore((s) => s.addPending)
  const removePending = useChatWorkspaceStore((s) => s.removePending)
  const clearPending = useChatWorkspaceStore((s) => s.clearPending)

  const newChatLabel = t('chat.newChat')
  const quote = workspaceChat?.quote ?? null

  const handleSend = async (message: string, media?: MediaItem[]) => {
    const wasNew = session.title === newChatLabel
    await chat.sendMessageTo(session.id, message, undefined, media)
    clearPending(session.id)
    if (wasNew) {
      chat.renameSession(session.id, deriveChatTitle(message, media, t))
    }
  }

  return (
    <div className="sidechat-body flex flex-col h-full min-h-0 bg-sidechat border border-sidechat-border rounded-xl shadow-[var(--shadow)] overflow-hidden">
      {/* Header: title + dock-back / close */}
      <div className="flex-shrink-0 flex items-center justify-between gap-2 px-3 py-2.5 border-b border-border">
        <span className="truncate text-[13px] font-semibold text-foreground">
          {session.title || newChatLabel}
        </span>
        <div className="flex items-center gap-0.5 flex-shrink-0">
          <button
            type="button"
            title={t('chat.dockBack')}
            onClick={onDockBack}
            className="p-1 rounded hover:bg-accent text-muted-foreground"
          >
            <ArrowLeftToLine className="h-3.5 w-3.5" />
          </button>
          <DeleteChatButton onDelete={onDelete} className="p-1 hover:bg-accent" />
          <button
            type="button"
            title={t('chat.hideChat')}
            onClick={onClose}
            className="p-1 rounded hover:bg-accent text-muted-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Sub-chat: "discussing this passage" banner (Plan D / Chunk 11) */}
      {quote && (
        <div className="flex-shrink-0 flex gap-2 mx-3 mt-3 px-3 py-2 rounded-lg bg-accent-soft border-l-[3px] border-primary-soft-border">
          <Quote className="h-3.5 w-3.5 text-primary flex-shrink-0 mt-0.5" />
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.07em] text-primary">
              {t('chat.discussingPassage')}
            </p>
            <p className="mt-0.5 text-xs text-foreground line-clamp-3">{quote}</p>
          </div>
        </div>
      )}

      <ChatPanel
        variant="dock"
        contextType="notebook"
        messages={chat.getMessages(session.id)}
        isStreaming={chat.getIsSending(session.id)}
        contextIndicators={null}
        onSendMessage={(message, _model, media) => handleSend(message, media)}
        notebookId={notebookId}
        chatScopeId={session.id}
        autoFocus={autoFocus}
        composerMaxHeight={120}
        // Per-chat model picker sits in the input box's toolbar row (mirrors the
        // dock); each popped panel runs its own model and surfaces the active one.
        composerToolbar={
          <ChatModelPicker
            compact
            value={session.model_override ?? null}
            onChange={(model) => chat.setSessionModelOverride(session.id, model)}
            disabled={chat.getIsSending(session.id)}
          />
        }
        emptyStateTitle={quote ? t('chat.passageEmptyTitle') : t('chat.emptyTitle')}
        emptyStateHelper={quote ? t('chat.passageEmptyHelper') : t('chat.emptyHelper')}
        draft={workspaceChat?.draft ?? ''}
        onDraftChange={(v) => setDraft(session.id, v)}
        pending={workspaceChat?.pending ?? []}
        onAddPending={(item) => addPending(session.id, item)}
        onRemovePending={(index) => removePending(session.id, index)}
      />
    </div>
  )
}
