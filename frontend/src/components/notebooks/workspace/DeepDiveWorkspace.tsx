'use client'

import { useState, useEffect, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  closestCenter,
  type DragEndEvent,
} from '@dnd-kit/core'
import { SortableContext, arrayMove, horizontalListSortingStrategy } from '@dnd-kit/sortable'
import { ArrowLeft, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { NotebookHeader } from '@/app/(dashboard)/notebooks/components/NotebookHeader'
import { ChatColumn } from '@/app/(dashboard)/notebooks/components/ChatColumn'
import { PanelTrack } from './PanelTrack'
import { PanelCard } from './PanelCard'
import { PoppedChatPanel } from '@/components/notebooks/chat/PoppedChatPanel'
import { PassageSelectionMenu } from './PassageSelectionMenu'
import { useNotebookColumnsStore } from '@/lib/stores/notebook-columns-store'
import { useChatWorkspaceStore } from '@/lib/stores/chat-workspace-store'
import { useNotebookWorkspaceStrict } from './NotebookWorkspaceProvider'
import { useTranslation } from '@/lib/hooks/use-translation'

const DOCK = 'dock'

/**
 * Dual-Panel Deep Dive (tier 3 of the three-tier flow). Renders the active Main
 * Chat (the dock, scoped to the `activeChatId` from the route) plus its Side
 * Chats as resizable, reorderable panels in the horizontal track. Sources/Notes
 * no longer live here — they moved to the global utility drawer — and the dock's
 * internal chat-list rail is gone too: switching Main Chats happens back in the
 * Gallery, reachable via the "Back to Gallery" control in the header.
 */
export function DeepDiveWorkspace({ activeChatId }: { activeChatId: string }) {
  const { t } = useTranslation()
  const router = useRouter()
  const {
    notebookId,
    notebook,
    chat,
    contextStats,
    dataError,
    sourcesLoading,
    notesLoading,
    sources,
    notes,
    contextSelections,
  } = useNotebookWorkspaceStrict()

  // Panel-track layout state (per-panel widths + maximize).
  const { widths, maximized, setWidth, toggleMaximized, setMaximized } = useNotebookColumnsStore()

  // Multi-chat workspace state (open/popped chats, anchor order).
  const wsChats = useChatWorkspaceStore((s) => s.chats)
  const panelOrder = useChatWorkspaceStore((s) => s.panelOrder)
  const openChat = useChatWorkspaceStore((s) => s.openChat)
  const popChat = useChatWorkspaceStore((s) => s.popChat)
  const closeChat = useChatWorkspaceStore((s) => s.closeChat)
  const setChatWidth = useChatWorkspaceStore((s) => s.setChatWidth)
  const reorderPanels = useChatWorkspaceStore((s) => s.reorderPanels)

  // Freshly-spawned side chat that should grab focus / be popped once it lands.
  const [pendingFocusId, setPendingFocusId] = useState<string | null>(null)
  const [pendingPopId, setPendingPopId] = useState<string | null>(null)

  // Drive the active Main Chat from the route. If the routed id is a side chat,
  // dock its parent main and pop the side chat (once); otherwise dock the routed
  // main directly (tolerates a just-created session not yet in the list).
  const routedSideHandled = useRef<string | null>(null)
  useEffect(() => {
    if (!activeChatId) return
    const routed = chat.sessions.find((s) => s.id === activeChatId)
    const parentId = routed?.parent_session_id ?? null
    openChat(parentId ?? activeChatId)
    if (parentId && routedSideHandled.current !== activeChatId) {
      routedSideHandled.current = activeChatId
      popChat(activeChatId)
      setPendingFocusId(activeChatId)
    }
  }, [activeChatId, chat.sessions, openChat, popChat])

  // Popped-out chats (live in the track). Must be OPEN + undocked.
  const poppedIds = useMemo(
    () => Object.keys(wsChats).filter((id) => wsChats[id]?.open && wsChats[id]?.docked === false),
    [wsChats]
  )
  const poppedIdSet = useMemo(() => new Set(poppedIds), [poppedIds])

  // Display order: the dock anchor + every top-level popped chat, each followed
  // by its nested sub-chats. Sources/Notes are intentionally excluded (drawer).
  const displayOrder = useMemo(() => {
    const parentOf = (id: string) => wsChats[id]?.parentId ?? null
    const hasPresentParent = (id: string) => {
      const p = parentOf(id)
      return !!p && poppedIdSet.has(p)
    }
    const childChatsOf = (token: string) =>
      panelOrder.filter((c) => poppedIdSet.has(c) && parentOf(c) === token)

    const anchors = panelOrder.filter((tok) =>
      tok === DOCK ? true : poppedIdSet.has(tok) && !hasPresentParent(tok)
    )
    const seq: string[] = []
    const visit = (tok: string) => {
      seq.push(tok)
      childChatsOf(tok).forEach(visit)
    }
    anchors.forEach(visit)
    poppedIds.forEach((id) => {
      if (!seq.includes(id)) seq.push(id)
    })
    // Guarantee the dock is present even if a stale panelOrder dropped it.
    if (!seq.includes(DOCK)) seq.unshift(DOCK)
    return seq
  }, [panelOrder, wsChats, poppedIdSet, poppedIds])

  // Maximize: focused panel fills; its sub-chats stay visible; everything else
  // hides. A stale maximize id is ignored and cleared.
  const effectiveMax =
    maximized && (maximized === DOCK || poppedIdSet.has(maximized)) ? maximized : null
  useEffect(() => {
    if (maximized && !effectiveMax) setMaximized(null)
  }, [maximized, effectiveMax, setMaximized])

  const maxVisible = useMemo(() => {
    if (!effectiveMax) return null
    const set = new Set<string>([effectiveMax])
    const addKids = (tok: string) => {
      panelOrder
        .filter((c) => poppedIdSet.has(c) && (wsChats[c]?.parentId ?? null) === tok)
        .forEach((c) => {
          set.add(c)
          addKids(c)
        })
    }
    addKids(effectiveMax)
    return set
  }, [effectiveMax, panelOrder, poppedIdSet, wsChats])

  const isCardVisible = (id: string) => !maxVisible || maxVisible.has(id)
  const visibleTokens = displayOrder.filter(isCardVisible)
  // A single visible panel (lone dock or a maximized panel) fills the canvas.
  const fillSingle = visibleTokens.length === 1

  // Spawn a sub-chat from a selected passage → pop + focus once it lands.
  const handleCreateSubChat = async (parentId: string, quote: string) => {
    const session = await chat.createSubChat(parentId, quote)
    if (session) {
      setPendingPopId(session.id)
      setPendingFocusId(session.id)
    }
  }

  // Track "+" — spawn a new standalone side chat next to the dock.
  const handleNewSidePanel = async () => {
    const session = await chat.createSidePanel(t('chat.newChat'))
    if (session) {
      setPendingPopId(session.id)
      setPendingFocusId(session.id)
    }
  }

  useEffect(() => {
    if (!pendingPopId) return
    if (wsChats[pendingPopId]) {
      popChat(pendingPopId)
      setPendingPopId(null)
    }
  }, [pendingPopId, wsChats, popChat])

  useEffect(() => {
    if (!pendingFocusId) return
    const timer = setTimeout(() => setPendingFocusId(null), 1500)
    return () => clearTimeout(timer)
  }, [pendingFocusId])

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  const handleDragEnd = (e: DragEndEvent) => {
    const { active, over } = e
    if (!over) return
    const activeId = String(active.id)
    const overId = String(over.id)
    if (activeId === overId) return
    const from = panelOrder.indexOf(activeId)
    const to = panelOrder.indexOf(overId)
    if (from !== -1 && to !== -1) reorderPanels(arrayMove(panelOrder, from, to))
  }

  const chatLoading = sourcesLoading || notesLoading

  const renderCard = (token: string) => {
    const fills = effectiveMax === token || fillSingle
    if (token === DOCK) {
      return (
        <PanelCard
          key="dock"
          id="dock"
          width={widths.dock}
          onWidthChange={(w) => setWidth('dock', w)}
          maximized={fills}
          onToggleMaximize={() => toggleMaximized('dock')}
        >
          <ChatColumn
            notebookId={notebookId}
            chat={chat}
            contextStats={contextStats}
            loading={chatLoading}
            error={dataError}
          />
        </PanelCard>
      )
    }
    const session = chat.sessions.find((s) => s.id === token)
    if (!session) return null
    return (
      <PanelCard
        key={token}
        id={token}
        width={wsChats[token]?.width ?? 480}
        onWidthChange={(w) => setChatWidth(token, w)}
        maximized={fills}
        onToggleMaximize={() => toggleMaximized(token)}
        scrollIntoViewOnMount={pendingFocusId === token}
      >
        <PoppedChatPanel
          notebookId={notebookId}
          session={session}
          chat={chat}
          sources={sources ?? []}
          notes={notes ?? []}
          notebookContextSelections={contextSelections}
          autoFocus={pendingFocusId === token}
          onDockBack={() => router.push(`/notebooks/${notebookId}/chat/${token}`)}
          onClose={() => closeChat(token)}
          onDelete={() => chat.deleteSession(token)}
          onPromote={() => chat.promoteToMain(token)}
        />
      </PanelCard>
    )
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex-shrink-0 flex items-center gap-3 px-6 py-3 border-b border-border">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push(`/notebooks/${notebookId}`)}
          className="flex-shrink-0 gap-1.5 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          {t('gallery.backToGallery')}
        </Button>
        <div className="h-5 w-px bg-border" aria-hidden />
        <div className="min-w-0 flex-1">{notebook && <NotebookHeader notebook={notebook} />}</div>
      </div>

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
          <PanelTrack className="flex-1 px-6 pt-4 pb-[18px]" showSpacer={!fillSingle}>
            <SortableContext items={visibleTokens} strategy={horizontalListSortingStrategy}>
              {visibleTokens.map(renderCard)}
            </SortableContext>
            {!effectiveMax && (
              <button
                type="button"
                onClick={handleNewSidePanel}
                title={t('chat.newChat')}
                aria-label={t('chat.newChat')}
                className="flex-shrink-0 self-stretch w-12 flex items-center justify-center rounded-xl border border-dashed border-border text-muted-foreground transition-colors hover:border-primary hover:bg-accent-soft hover:text-primary"
              >
                <Plus className="h-5 w-5" />
              </button>
            )}
          </PanelTrack>
          <PassageSelectionMenu onChatAboutPassage={handleCreateSubChat} />
        </div>
      </DndContext>
    </div>
  )
}
