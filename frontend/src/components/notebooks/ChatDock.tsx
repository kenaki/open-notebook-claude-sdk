'use client'

import { useEffect, useMemo } from 'react'
import { SortableContext, horizontalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ChatPanel } from '@/components/source/ChatPanel'
import { ChatModelPicker } from '@/components/notebooks/ChatModelPicker'
import { SideChatDefaultMenu } from '@/components/notebooks/SideChatDefaultMenu'
import { Button } from '@/components/ui/button'
import { Plus, X, ArrowUpRight } from 'lucide-react'
import { useChatWorkspaceStore } from '@/lib/stores/chat-workspace-store'
import { useChatDefaultsStore } from '@/lib/stores/chat-defaults-store'
import { useTranslation } from '@/lib/hooks/use-translation'
import { BaseChatSession, NotebookChatSession, MediaItem } from '@/lib/types/api'
import type { useNotebookChat } from '@/lib/hooks/useNotebookChat'

// Derive a chat title from the first message (Plan D / Chunk 12). Text wins;
// otherwise fall back to the single filename or "N attachments" (handoff
// §"Media attachments"). Shared with PoppedChatPanel.
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

// Sortable id prefix for dock tabs — lets the page's single DndContext tell a
// tab drag (reorder / pop-out) apart from a panel drag.
export const TAB_DND_PREFIX = 'tab:'

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
  // Pop-out is only meaningful where the track can render popped panels
  // (desktop). On the mobile tabbed view it's hidden so a popped chat can't
  // vanish with nowhere to render (mobile layout is Plan E's scope).
  enablePopOut?: boolean
}

/**
 * The Chat Dock panel (Plan C). A flat list of **docked** chats as drag-orderable
 * tabs (reorder + pop-out via @dnd-kit, Chunk 8), a dock-header model picker
 * bound to the global `claude_agent` config (Decision 8), and a context meter
 * pill. Only the active docked tab renders its conversation; popped chats render
 * as their own panels in the track. The page owns the DndContext; this component
 * provides the tab SortableContext and the pop-out action.
 */
export function ChatDock({ notebookId, chat, contextStats, enablePopOut = true }: ChatDockProps) {
  const { t } = useTranslation()
  const chats = useChatWorkspaceStore((s) => s.chats)
  const order = useChatWorkspaceStore((s) => s.order)
  const syncChats = useChatWorkspaceStore((s) => s.syncChats)
  const setActiveChat = useChatWorkspaceStore((s) => s.setActiveChat)
  const setDraft = useChatWorkspaceStore((s) => s.setDraft)
  const setDocked = useChatWorkspaceStore((s) => s.setDocked)
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
  // parent_session_id) as popped, anchored panels after a reload (Chunk 11).
  useEffect(() => {
    syncChats(sessions.map((s) => ({ id: s.id, parent_session_id: s.parent_session_id, quote: s.quote })))
  }, [sessions, syncChats])

  // Docked tabs only (popped chats live in the track), ordered by store order.
  const dockedSessions = useMemo(() => {
    const isDocked = (id: string) => chats[id]?.docked !== false // default docked
    const ordered = order
      .map((id) => sessions.find((s) => s.id === id))
      .filter((s): s is NotebookChatSession => !!s && isDocked(s.id))
    const extras = sessions.filter((s) => !order.includes(s.id) && isDocked(s.id))
    return [...ordered, ...extras]
  }, [order, sessions, chats])

  // The active docked tab. If the hook's current session isn't docked (e.g. it
  // was just popped out), fall back to the first docked tab.
  const activeDockedId = useMemo(() => {
    if (currentSessionId && dockedSessions.some((s) => s.id === currentSessionId)) {
      return currentSessionId
    }
    return dockedSessions[0]?.id ?? null
  }, [currentSessionId, dockedSessions])

  // Keep the hook's current session pointed at a docked tab.
  useEffect(() => {
    if (activeDockedId && activeDockedId !== currentSessionId) {
      chat.switchSession(activeDockedId)
      setActiveChat(activeDockedId)
    }
  }, [activeDockedId, currentSessionId, chat, setActiveChat])

  const activeChat = activeDockedId ? chats[activeDockedId] : undefined

  const handleSwitch = (id: string) => {
    setActiveChat(id)
    chat.switchSession(id)
  }

  const handlePopOut = (id: string) => {
    setDocked(id, false)
    // If we popped the active tab, hand the dock to the next docked chat.
    if (id === activeDockedId) {
      const next = dockedSessions.find((s) => s.id !== id)
      if (next) handleSwitch(next.id)
    }
  }

  const handleSend = async (message: string, media?: MediaItem[]) => {
    const target = activeDockedId
    const wasNew = !!target && sessions.find((s) => s.id === target)?.title === newChatLabel
    await chat.sendMessageTo(target, message, undefined, media)
    if (target) clearPending(target)
    if (wasNew && target) {
      chat.renameSession(target, deriveChatTitle(message, media, t))
    }
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

  // The dock header's ChatModelPicker drives the *active chat's* per-session
  // model override, so each tab can talk to a different model (popped panels
  // carry their own picker). The global Claude Agent default still lives in
  // Settings (ClaudeAgentModelCard). See ChatModelPicker for the value scheme.
  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeDockedId),
    [sessions, activeDockedId]
  )
  const activeOverride = activeSession?.model_override ?? chat.pendingModelOverride ?? null

  const draftProps = activeChat
    ? { draft: activeChat.draft, onDraftChange: (v: string) => setDraft(activeChat.id, v) }
    : {}

  const tabItemIds = dockedSessions.map((s) => `${TAB_DND_PREFIX}${s.id}`)
  const canClose = sessions.length > 1

  // Tab strip sits *above* the input box (composerHeader); the active-chat model
  // picker + context meter + settings cog drop into the input box's utility
  // toolbar row (composerToolbar), separated from the typing area.
  const dockTabs = (
    <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5">
      {dockedSessions.length === 0 ? (
        <div className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs bg-accent-soft text-foreground">
          <span className="truncate max-w-[140px]">{newChatLabel}</span>
        </div>
      ) : (
        <SortableContext items={tabItemIds} strategy={horizontalListSortingStrategy}>
          {dockedSessions.map((session) => (
            <SortableTab
              key={session.id}
              session={session}
              isActive={session.id === activeDockedId}
              canClose={canClose}
              newChatLabel={newChatLabel}
              onSwitch={() => handleSwitch(session.id)}
              onPopOut={() => handlePopOut(session.id)}
              onClose={() => chat.deleteSession(session.id)}
              enablePopOut={enablePopOut}
              popOutLabel={t('chat.popOut')}
              closeLabel={t('chat.closeChat')}
            />
          ))}
        </SortableContext>
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-7 w-7 flex-shrink-0 rounded-full"
        title={t('chat.newChat')}
        onClick={() => chat.createSession(newChatLabel)}
      >
        <Plus className="h-4 w-4" />
      </Button>
    </div>
  )

  const dockControls = (
    <>
      <ChatModelPicker compact value={activeOverride} onChange={chat.setModelOverride} />
      <span className="text-[11px] text-text-3 truncate">{meterText}</span>
      <SideChatDefaultMenu
        value={sideChatModel}
        onChange={(model) => setSideChatModel(notebookId, model)}
      />
    </>
  )

  return (
    <div className="flex flex-col h-full min-h-0 bg-card border border-border rounded-xl shadow-[var(--shadow)] overflow-hidden">
      {/* Conversation fills the card; tabs sit above the box, controls inside it. */}
      <ChatPanel
        variant="dock"
        contextType="notebook"
        messages={chat.getMessages(activeDockedId)}
        isStreaming={chat.getIsSending(activeDockedId)}
        contextIndicators={null}
        onSendMessage={(message, _model, media) => handleSend(message, media)}
        notebookId={notebookId}
        pending={activeChat?.pending ?? []}
        onAddPending={activeDockedId ? (item) => addPending(activeDockedId, item) : undefined}
        onRemovePending={activeDockedId ? (index) => removePending(activeDockedId, index) : undefined}
        // Tag AI bodies with the active session id so a passage selection can be
        // traced back to its parent chat for sub-chat creation (Chunk 11).
        chatScopeId={activeDockedId ?? undefined}
        composerMaxHeight={140}
        composerHeader={dockTabs}
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
  )
}

interface SortableTabProps {
  session: BaseChatSession
  isActive: boolean
  canClose: boolean
  enablePopOut: boolean
  newChatLabel: string
  popOutLabel: string
  closeLabel: string
  onSwitch: () => void
  onPopOut: () => void
  onClose: () => void
}

/**
 * A single dock tab. Draggable via @dnd-kit (distance-activated so a click still
 * switches tabs); drop onto another tab to reorder, or onto the track drop-zone
 * to pop the chat out.
 */
function SortableTab({
  session,
  isActive,
  canClose,
  enablePopOut,
  newChatLabel,
  popOutLabel,
  closeLabel,
  onSwitch,
  onPopOut,
  onClose,
}: SortableTabProps) {
  const { setNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({
    id: `${TAB_DND_PREFIX}${session.id}`,
  })

  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(transform),
    transition,
    zIndex: isDragging ? 40 : undefined,
    opacity: isDragging ? 0.6 : undefined,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={onSwitch}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSwitch()
        }
      }}
      className={`group flex items-center gap-1.5 pl-3.5 pr-2 py-1.5 rounded-full text-xs cursor-pointer transition-colors flex-shrink-0 touch-none ${
        isActive ? 'bg-accent-soft text-foreground' : 'text-muted-foreground hover:bg-accent'
      }`}
    >
      <span className="truncate max-w-[140px]">{session.title || newChatLabel}</span>
      {/* Pop-out (↗) */}
      {enablePopOut && (
        <button
          type="button"
          title={popOutLabel}
          className="p-0.5 rounded hover:bg-background"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation()
            onPopOut()
          }}
        >
          <ArrowUpRight className="h-3 w-3" />
        </button>
      )}
      {/* Close (✕) — keep at least one chat */}
      <button
        type="button"
        title={closeLabel}
        disabled={!canClose}
        className="p-0.5 rounded hover:bg-background disabled:opacity-30 disabled:hover:bg-transparent"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation()
          if (canClose) onClose()
        }}
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  )
}
