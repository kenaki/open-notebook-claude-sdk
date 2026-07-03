'use client'

import { useEffect, useMemo } from 'react'
import { ChatPanel } from '@/components/source/chat'
import { ChatModelPicker } from './ChatModelPicker'
import { ContextPreviewPopover } from './ContextPreview'
import { SideChatDefaultMenu } from './SideChatDefaultMenu'
import { SideChatsMenu } from './SideChatsMenu'
import { useChatWorkspaceStore } from '@/lib/stores/chat-workspace-store'
import { useChatDefaultsStore } from '@/lib/stores/chat-defaults-store'
import { useTranslation } from '@/lib/hooks/use-translation'
import { MediaItem } from '@/lib/types/api'
import type { useNotebookChat } from '@/lib/hooks/useNotebookChat'

// Derive a chat title from the first message (Plan D / Chunk 12). Text wins;
// otherwise fall back to the single filename or "N attachments" (handoff
// §"Media attachments"). Shared with PoppedChatPanel and ChatSidebar.
export function deriveChatTitle(
  message: string,
  media: MediaItem[] | undefined,
  t: (key: string) => string,
): string {
  const text = message.trim()
  if (text) return text.length > 30 ? `${text.slice(0, 30)}...` : text
  if (media && media.length > 0) {
    return media.length === 1
      ? media[0].label
      : t('chat.attachmentsCount').replace('{count}', media.length.toString())
  }
  return text
}

interface ChatDockContextStats {
  sourcesInsights: number
  sourcesFull: number
  notesCount: number
  tokenCount?: number
  charCount?: number
}

interface ChatDockProps {
  notebookId: string
  // The single multiplexed chat hook (lifted to the page).
  chat: ReturnType<typeof useNotebookChat>
  contextStats: ChatDockContextStats
  // Retained for back-compat with ChatColumn's mobile call; the dock no longer
  // pops chats out (the sidebar switches the active main; panels come from the
  // track "+" / side-chats control instead of per-tab pop-out).
  enablePopOut?: boolean
}

/**
 * The Chat Dock panel (Sidebar redesign / Chunk 2). A left **sidebar rail** lists
 * the notebook's MAIN chats (searchable, recency-ordered — {@link ChatSidebar});
 * the right pane renders the active main's conversation. A dock-header model
 * picker drives the active chat's per-session override, alongside a context meter
 * and the side-chat default cog. Side chats live as popped panels in the track
 * (page.tsx), not here.
 */
export function ChatDock({ notebookId, chat, contextStats }: ChatDockProps) {
  const { t } = useTranslation()
  const chats = useChatWorkspaceStore((s) => s.chats)
  const activeChatId = useChatWorkspaceStore((s) => s.activeChatId)
  const syncChats = useChatWorkspaceStore((s) => s.syncChats)
  const openChat = useChatWorkspaceStore((s) => s.openChat)
  const setDraft = useChatWorkspaceStore((s) => s.setDraft)
  const addPending = useChatWorkspaceStore((s) => s.addPending)
  const removePending = useChatWorkspaceStore((s) => s.removePending)
  const clearPending = useChatWorkspaceStore((s) => s.clearPending)

  // Per-notebook default model for side chats (annotative sub-chats), set via
  // the dock header's settings cog and applied at sub-chat creation time.
  const sideChatModel = useChatDefaultsStore((s) => s.sideChatModel[notebookId] ?? null)
  const setSideChatModel = useChatDefaultsStore((s) => s.setSideChatModel)

  const { sessions, currentSessionId } = chat
  const newChatLabel = t('chat.newChat')

  // Reconcile the workspace store with the live session list. Passing the full
  // session objects lets the store re-hydrate persisted sub-chats (those with a
  // parent_session_id) as closed entries and auto-open the most-recent main.
  useEffect(() => {
    syncChats(sessions.map((s) => ({ id: s.id, parent_session_id: s.parent_session_id, quote: s.quote })))
  }, [sessions, syncChats])

  // The active main shown in the dock body (open + docked). Null → empty state.
  const activeMainId =
    activeChatId && chats[activeChatId]?.open && chats[activeChatId]?.docked !== false
      ? activeChatId
      : null

  // Keep the hook's current session pointed at the active main so its message
  // stream stays live.
  useEffect(() => {
    if (activeMainId && activeMainId !== currentSessionId) {
      chat.switchSession(activeMainId)
    }
  }, [activeMainId, currentSessionId, chat])

  const activeChat = activeMainId ? chats[activeMainId] : undefined

  const handleOpen = (id: string) => {
    openChat(id)
    chat.switchSession(id)
  }

  const handleSend = async (message: string, media?: MediaItem[]): Promise<{ ok: boolean }> => {
    let target = activeMainId
    // No main open (all hidden) → spin one up and open it before sending.
    if (!target) {
      const session = await chat.createSession(newChatLabel)
      // Creation failed (already toasted) — signal failure so the composer
      // restores the draft (Track A / A2).
      if (!session) return { ok: false }
      target = session.id
      handleOpen(session.id)
    }
    const wasNew = sessions.find((s) => s.id === target)?.title === newChatLabel
    // sendMessageTo submits the job (202) and returns immediately; isStreaming
    // (chat.getIsSending) derives from the jobs-store for the rest of the lifecycle.
    const result = await chat.sendMessageTo(target, message, undefined, media)
    // Only finalize on success: clearing pending media / renaming on a failed
    // send would discard the user's staged attachments and draft (Track A / A2).
    if (result.ok) {
      clearPending(target)
      if (wasNew) chat.renameSession(target, deriveChatTitle(message, media, t))
    }
    return result
  }

  // Context meter pill: "N sources · M notes · k tokens".
  const sourceCount = contextStats.sourcesInsights + contextStats.sourcesFull
  const tokenCount = contextStats.tokenCount ?? 0
  const tokenLabel = tokenCount >= 1000 ? `${Math.round(tokenCount / 1000)}k` : `${tokenCount}`
  const meterText = [
    t('chat.meterSources').replace('{count}', sourceCount.toString()),
    t('chat.meterNotes').replace('{count}', contextStats.notesCount.toString()),
    t('chat.meterTokens').replace('{count}', tokenLabel),
  ].join(' · ')

  // The dock header's ChatModelPicker drives the active main's per-session model
  // override. See ChatModelPicker for the value scheme.
  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeMainId),
    [sessions, activeMainId]
  )
  const activeOverride = activeSession?.model_override ?? chat.pendingModelOverride ?? null

  const draftProps = activeChat
    ? { draft: activeChat.draft, onDraftChange: (v: string) => setDraft(activeChat.id, v) }
    : {}

  const dockControls = (
    <>
      <ChatModelPicker compact value={activeOverride} onChange={chat.setModelOverride} />
      <ContextPreviewPopover
        contextData={chat.contextData}
        tokenCount={tokenCount}
        charCount={contextStats.charCount ?? 0}
        sourceCount={sourceCount}
        notesCount={contextStats.notesCount}
      >
        <span className="text-[11px] text-text-3 truncate">{meterText}</span>
      </ContextPreviewPopover>
      {activeMainId && (
        <SideChatsMenu sideSessions={chat.sideSessionsOf(activeMainId)} onOpen={openChat} />
      )}
      <SideChatDefaultMenu
        value={sideChatModel}
        onChange={(model) => setSideChatModel(notebookId, model)}
      />
    </>
  )

  return (
    <div className="flex h-full min-h-0 bg-card border border-border rounded-xl shadow-[var(--shadow)] overflow-hidden">
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        <ChatPanel
          variant="dock"
          contextType="notebook"
          messages={chat.getMessages(activeMainId)}
          isStreaming={chat.getIsSending(activeMainId)}
          activeProgress={chat.getActiveProgress(activeMainId)}
          contextIndicators={null}
          onSendMessage={(message, _model, media) => handleSend(message, media)}
          notebookId={notebookId}
          pending={activeChat?.pending ?? []}
          onAddPending={activeMainId ? (item) => addPending(activeMainId, item) : undefined}
          onRemovePending={activeMainId ? (index) => removePending(activeMainId, index) : undefined}
          // Tag AI bodies with the active session id so a passage selection can be
          // traced back to its parent chat for sub-chat creation (Chunk 11).
          chatScopeId={activeMainId ?? undefined}
          composerMaxHeight={140}
          composerToolbar={dockControls}
          emptyStateTitle={t('chat.emptyTitle')}
          emptyStateHelper={t('chat.emptyHelper')}
          suggestions={[
            t('chat.suggestionSummarize'),
            t('chat.suggestionQuestions'),
            t('chat.suggestionConnections'),
          ]}
          {...draftProps}
        />
      </div>
    </div>
  )
}
