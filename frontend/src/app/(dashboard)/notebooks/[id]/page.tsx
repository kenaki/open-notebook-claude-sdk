'use client'

import { useState, useEffect, useMemo } from 'react'
import { useParams } from 'next/navigation'
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  closestCenter,
  type DragEndEvent,
} from '@dnd-kit/core'
import { SortableContext, arrayMove, horizontalListSortingStrategy } from '@dnd-kit/sortable'
import { AppShell } from '@/components/layout/AppShell'
import { NotebookHeader } from '../components/NotebookHeader'
import { SourcesColumn } from '../components/SourcesColumn'
import { NotesColumn } from '../components/NotesColumn'
import { ChatColumn } from '../components/ChatColumn'
import { useNotebook } from '@/lib/hooks/use-notebooks'
import { useNotebookSources } from '@/lib/hooks/use-sources'
import { useNotes } from '@/lib/hooks/use-notes'
import { useNotebookChat } from '@/lib/hooks/useNotebookChat'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useNotebookColumnsStore } from '@/lib/stores/notebook-columns-store'
import {
  useChatWorkspaceStore,
  FIXED_PANEL_IDS,
} from '@/lib/stores/chat-workspace-store'
import { PanelTrack } from '@/components/notebooks/PanelTrack'
import { PanelCard } from '@/components/notebooks/PanelCard'
import { PoppedChatPanel } from '@/components/notebooks/PoppedChatPanel'
import { PassageSelectionMenu } from '@/components/notebooks/PassageSelectionMenu'
import { useIsDesktop } from '@/lib/hooks/use-media-query'
import { useTranslation } from '@/lib/hooks/use-translation'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FileText, StickyNote, MessageSquare, Plus } from 'lucide-react'
import {
  applyBulkSourceContext,
  applyBulkNoteContext,
  computeSourceSelections,
  computeNoteSelections,
  type SourceContextDefault,
  type SourceBulkAction,
  type NoteContextDefault,
} from '@/lib/utils/source-context'

// Re-exported from the shared types module for backward compatibility; several
// components historically import these from this route file.
import type { ContextMode, ContextSelections } from '@/lib/types/notebook-context'
export type { ContextMode, ContextSelections }

const FIXED = FIXED_PANEL_IDS as readonly string[]

export default function NotebookPage() {
  const { t } = useTranslation()
  const params = useParams()

  // Ensure the notebook ID is properly decoded from URL
  const notebookId = params?.id ? decodeURIComponent(params.id as string) : ''

  const { data: notebook, isLoading: notebookLoading } = useNotebook(notebookId)
  const {
    sources,
    isLoading: sourcesLoading,
    refetch: refetchSources,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useNotebookSources(notebookId)
  const { data: notes, isLoading: notesLoading } = useNotes(notebookId)

  // Panel-track layout state (collapse + per-panel widths + maximize)
  const {
    sourcesCollapsed,
    notesCollapsed,
    widths,
    maximized,
    setWidth,
    toggleMaximized,
    setMaximized,
  } = useNotebookColumnsStore()

  // Multi-chat workspace state (open/popped chats, anchor order)
  const wsChats = useChatWorkspaceStore((s) => s.chats)
  const panelOrder = useChatWorkspaceStore((s) => s.panelOrder)
  const openChat = useChatWorkspaceStore((s) => s.openChat)
  const popChat = useChatWorkspaceStore((s) => s.popChat)
  const closeChat = useChatWorkspaceStore((s) => s.closeChat)
  const setChatWidth = useChatWorkspaceStore((s) => s.setChatWidth)
  const reorderPanels = useChatWorkspaceStore((s) => s.reorderPanels)

  // Detect desktop to avoid double-mounting the chat hook / dock
  const isDesktop = useIsDesktop()

  // Mobile tab state (Sources, Notes, or Chat)
  const [mobileActiveTab, setMobileActiveTab] = useState<'sources' | 'notes' | 'chat'>('chat')

  // Sub-chats (Chunk 11): id of a freshly-spawned sub-chat whose composer should
  // grab focus once its popped panel mounts (after the session list refetches).
  const [pendingFocusId, setPendingFocusId] = useState<string | null>(null)

  // A freshly-created standalone side chat (track "+") that must be popped out as
  // soon as the workspace store registers it (new sessions default to docked).
  const [pendingPopId, setPendingPopId] = useState<string | null>(null)

  // Context selection state
  const [contextSelections, setContextSelections] = useState<ContextSelections>({
    sources: {},
    notes: {}
  })

  // The default context mode applied to sources as they load. A bulk
  // include/exclude updates this so sources loaded later via pagination follow
  // the same intent instead of reverting to "included" (#223/#915).
  const [sourceContextDefault, setSourceContextDefault] = useState<SourceContextDefault>('include')

  // Same idea for notes loaded later (notes are binary: included/off).
  const [noteContextDefault, setNoteContextDefault] = useState<NoteContextDefault>('include')

  // Initialize and update selections when sources load or change
  useEffect(() => {
    if (sources && sources.length > 0) {
      setContextSelections(prev => ({
        ...prev,
        sources: computeSourceSelections(prev.sources, sources, sourceContextDefault),
      }))
    }
  }, [sources, sourceContextDefault])

  useEffect(() => {
    if (notes && notes.length > 0) {
      setContextSelections(prev => ({
        ...prev,
        notes: computeNoteSelections(prev.notes, notes, noteContextDefault),
      }))
    }
  }, [notes, noteContextDefault])

  // Popped-out chats (live in the track, not the dock). Derived from the store,
  // which ChatDock keeps synced to the live session list. Must be OPEN — closed
  // chats (sidebar-only) never render even though their default docked is false.
  const poppedIds = useMemo(
    () =>
      Object.keys(wsChats).filter(
        (id) => wsChats[id]?.open && wsChats[id]?.docked === false
      ),
    [wsChats]
  )
  const poppedIdSet = useMemo(() => new Set(poppedIds), [poppedIds])

  // Single multiplexed chat hook (lifted here so the dock AND every popped panel
  // share one instance — Plan C / Chunk 8).
  const chat = useNotebookChat({
    notebookId,
    sources: sources ?? [],
    notes: notes ?? [],
    contextSelections,
    visibleSessionIds: poppedIds,
  })

  const chatLoading = sourcesLoading || notesLoading

  // Context meter stats for the dock.
  const contextStats = useMemo(() => {
    let sourcesInsights = 0
    let sourcesFull = 0
    let notesCount = 0
    ;(sources ?? []).forEach((source) => {
      const mode = contextSelections.sources[source.id]
      if (mode === 'insights') sourcesInsights++
      else if (mode === 'full') sourcesFull++
    })
    ;(notes ?? []).forEach((note) => {
      if (contextSelections.notes[note.id] === 'full') notesCount++
    })
    return {
      sourcesInsights,
      sourcesFull,
      notesCount,
      tokenCount: chat.tokenCount,
      charCount: chat.charCount,
    }
  }, [sources, notes, contextSelections, chat.tokenCount, chat.charCount])

  // --- Derived panel display order (handoff "ordering/nesting") -------------
  // Anchors = fixed panels + popped chats without a present parent; each anchor
  // is followed by its child chats (recursive). `parentId` is null until Plan D
  // adds sub-chats, so today every popped chat is a top-level anchor — but the
  // algorithm is built so sub-chats nest immediately right of their parent for
  // free, with an orphan fallback if the parent was closed.
  const displayOrder = useMemo(() => {
    const parentOf = (id: string) => wsChats[id]?.parentId ?? null
    const hasPresentParent = (id: string) => {
      const p = parentOf(id)
      return !!p && poppedIdSet.has(p)
    }
    const childChatsOf = (token: string) =>
      panelOrder.filter((c) => poppedIdSet.has(c) && parentOf(c) === token)

    const anchors = panelOrder.filter((tok) =>
      FIXED.includes(tok) ? true : poppedIdSet.has(tok) && !hasPresentParent(tok)
    )
    const seq: string[] = []
    const visit = (tok: string) => {
      seq.push(tok)
      childChatsOf(tok).forEach(visit)
    }
    anchors.forEach(visit)
    // Safety: any popped chat not yet in panelOrder (sync race) is appended.
    poppedIds.forEach((id) => {
      if (!seq.includes(id)) seq.push(id)
    })
    return seq
  }, [panelOrder, wsChats, poppedIdSet, poppedIds])

  // Maximize: focused panel fills; its sub-chats stay visible at fixed width;
  // everything else hides. A stale maximize id (panel docked back / closed) is
  // ignored and cleared.
  const effectiveMax =
    maximized && (FIXED.includes(maximized) || poppedIdSet.has(maximized)) ? maximized : null
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

  // Handler to update context selection
  const handleContextModeChange = (itemId: string, mode: ContextMode, type: 'source' | 'note') => {
    setContextSelections(prev => ({
      ...prev,
      [type === 'source' ? 'sources' : 'notes']: {
        ...(type === 'source' ? prev.sources : prev.notes),
        [itemId]: mode
      }
    }))
  }

  // Bulk-apply a context action (insights-only / full / exclude) to every
  // source at once (#223). Also records the action as the default for sources
  // loaded later (#915).
  const handleBulkSourceContext = (action: SourceBulkAction) => {
    setSourceContextDefault(action)
    setContextSelections(prev => ({
      ...prev,
      sources: applyBulkSourceContext(prev.sources, sources ?? [], action),
    }))
  }

  // Bulk include/exclude every note from the chat context at once (#223).
  const handleBulkNoteContext = (action: NoteContextDefault) => {
    setNoteContextDefault(action)
    setContextSelections(prev => ({
      ...prev,
      notes: applyBulkNoteContext(prev.notes, notes ?? [], action),
    }))
  }

  // Spawn a sub-chat from a selected passage (Chunk 11). createSubChat POSTs the
  // session (parent_session_id + quote); the refetch → ChatDock syncChats →
  // registers it as a CLOSED side chat (Chunk 2 visibility model). Mark it to be
  // popped + focused the moment it lands (mirrors the track "+" flow).
  const handleCreateSubChat = async (parentId: string, quote: string) => {
    const session = await chat.createSubChat(parentId, quote)
    if (session) {
      setPendingPopId(session.id)
      setPendingFocusId(session.id)
    }
  }

  // Track "+" button: spawn a new standalone side chat. Create it, then mark it
  // to be popped out + focused once syncChats registers it in the store.
  const handleNewSidePanel = async () => {
    const session = await chat.createSidePanel(t('chat.newChat'))
    if (session) {
      setPendingPopId(session.id)
      setPendingFocusId(session.id)
    }
  }

  // Open the freshly-created side chat as a popped panel the moment it appears in
  // the workspace store (new sessions land closed by default), then clear the flag.
  useEffect(() => {
    if (!pendingPopId) return
    if (wsChats[pendingPopId]) {
      popChat(pendingPopId)
      setPendingPopId(null)
    }
  }, [pendingPopId, wsChats, popChat])

  // Clear the pending-focus marker shortly after a sub-chat spawns so a later
  // re-mount (e.g. maximize toggle) doesn't re-steal focus.
  useEffect(() => {
    if (!pendingFocusId) return
    const timer = setTimeout(() => setPendingFocusId(null), 1500)
    return () => clearTimeout(timer)
  }, [pendingFocusId])

  // --- Drag & drop (reorder panels) -----------------------------------------
  // The dock tab strip is gone (Sidebar redesign / Chunk 2); only the fixed
  // panels + popped chat panels reorder now.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  const handleDragEnd = (e: DragEndEvent) => {
    const { active, over } = e
    if (!over) return
    const activeId = String(active.id)
    const overId = String(over.id)
    if (activeId === overId) return

    // Panel reorder (sources / notes / dock / popped chat).
    const from = panelOrder.indexOf(activeId)
    const to = panelOrder.indexOf(overId)
    if (from !== -1 && to !== -1) reorderPanels(arrayMove(panelOrder, from, to))
  }

  // Renders the right card for a display-order token.
  const renderCard = (token: string) => {
    if (token === 'sources') {
      return (
        <PanelCard
          key="sources"
          id="sources"
          width={widths.sources}
          onWidthChange={(w) => setWidth('sources', w)}
          minimized={sourcesCollapsed}
          maximized={effectiveMax === 'sources'}
          onToggleMaximize={() => toggleMaximized('sources')}
        >
          <SourcesColumn
            sources={sources}
            isLoading={sourcesLoading}
            notebookId={notebookId}
            notebookName={notebook?.name}
            onRefresh={refetchSources}
            contextSelections={contextSelections.sources}
            onContextModeChange={(sourceId, mode) => handleContextModeChange(sourceId, mode, 'source')}
            onBulkContextModeChange={handleBulkSourceContext}
            hasNextPage={hasNextPage}
            isFetchingNextPage={isFetchingNextPage}
            fetchNextPage={fetchNextPage}
          />
        </PanelCard>
      )
    }
    if (token === 'notes') {
      return (
        <PanelCard
          key="notes"
          id="notes"
          width={widths.notes}
          onWidthChange={(w) => setWidth('notes', w)}
          minimized={notesCollapsed}
          maximized={effectiveMax === 'notes'}
          onToggleMaximize={() => toggleMaximized('notes')}
        >
          <NotesColumn
            notes={notes}
            isLoading={notesLoading}
            notebookId={notebookId}
            contextSelections={contextSelections.notes}
            onContextModeChange={(noteId, mode) => handleContextModeChange(noteId, mode, 'note')}
            onBulkContextModeChange={handleBulkNoteContext}
          />
        </PanelCard>
      )
    }
    if (token === 'dock') {
      return (
        <PanelCard
          key="dock"
          id="dock"
          width={widths.dock}
          onWidthChange={(w) => setWidth('dock', w)}
          maximized={effectiveMax === 'dock'}
          onToggleMaximize={() => toggleMaximized('dock')}
        >
          <ChatColumn
            notebookId={notebookId}
            chat={chat}
            contextStats={contextStats}
            loading={chatLoading}
            error={!sources && !notes}
          />
        </PanelCard>
      )
    }
    // Popped-out chat panel.
    const session = chat.sessions.find((s) => s.id === token)
    if (!session) return null
    return (
      <PanelCard
        key={token}
        id={token}
        width={wsChats[token]?.width ?? 480}
        onWidthChange={(w) => setChatWidth(token, w)}
        maximized={effectiveMax === token}
        onToggleMaximize={() => toggleMaximized(token)}
        scrollIntoViewOnMount={pendingFocusId === token}
      >
        <PoppedChatPanel
          notebookId={notebookId}
          session={session}
          chat={chat}
          autoFocus={pendingFocusId === token}
          onDockBack={() => openChat(token)}
          onClose={() => closeChat(token)}
          onDelete={() => chat.deleteSession(token)}
        />
      </PanelCard>
    )
  }

  if (notebookLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (!notebook) {
    return (
      <AppShell>
        <div className="p-6">
          <h1 className="text-2xl font-bold mb-4">{t('notebooks.notFound')}</h1>
          <p className="text-muted-foreground">{t('notebooks.notFoundDesc')}</p>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className="flex flex-col flex-1 min-h-0">
        <div className="flex-shrink-0 px-6 py-3 border-b border-border">
          <NotebookHeader notebook={notebook} />
        </div>

        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            {/* Mobile: Tabbed interface - only render on mobile to avoid double-mounting */}
            {!isDesktop && (
              <div className="flex-1 min-h-0 flex flex-col p-6 lg:hidden">
                <div className="mb-4">
                  <Tabs value={mobileActiveTab} onValueChange={(value) => setMobileActiveTab(value as 'sources' | 'notes' | 'chat')}>
                    <TabsList className="grid w-full grid-cols-3">
                      <TabsTrigger value="sources" className="gap-2">
                        <FileText className="h-4 w-4" />
                        {t('navigation.sources')}
                      </TabsTrigger>
                      <TabsTrigger value="notes" className="gap-2">
                        <StickyNote className="h-4 w-4" />
                        {t('common.notes')}
                      </TabsTrigger>
                      <TabsTrigger value="chat" className="gap-2">
                        <MessageSquare className="h-4 w-4" />
                        {t('common.chat')}
                      </TabsTrigger>
                    </TabsList>
                  </Tabs>
                </div>

                {/* Mobile: Show only active tab */}
                <div className="flex-1 overflow-hidden">
                  {mobileActiveTab === 'sources' && (
                    <SourcesColumn
                      sources={sources}
                      isLoading={sourcesLoading}
                      notebookId={notebookId}
                      notebookName={notebook?.name}
                      onRefresh={refetchSources}
                      contextSelections={contextSelections.sources}
                      onContextModeChange={(sourceId, mode) => handleContextModeChange(sourceId, mode, 'source')}
                      onBulkContextModeChange={handleBulkSourceContext}
                      hasNextPage={hasNextPage}
                      isFetchingNextPage={isFetchingNextPage}
                      fetchNextPage={fetchNextPage}
                    />
                  )}
                  {mobileActiveTab === 'notes' && (
                    <NotesColumn
                      notes={notes}
                      isLoading={notesLoading}
                      notebookId={notebookId}
                      contextSelections={contextSelections.notes}
                      onContextModeChange={(noteId, mode) => handleContextModeChange(noteId, mode, 'note')}
                      onBulkContextModeChange={handleBulkNoteContext}
                    />
                  )}
                  {mobileActiveTab === 'chat' && (
                    <ChatColumn
                      notebookId={notebookId}
                      chat={chat}
                      contextStats={contextStats}
                      loading={chatLoading}
                      error={!sources && !notes}
                      enablePopOut={false}
                    />
                  )}
                </div>
              </div>
            )}

            {/* Desktop: horizontal resizable / draggable panel track */}
            {isDesktop && (
              <>
                <PanelTrack className="flex-1 px-6 pt-4 pb-[18px]">
                  <SortableContext items={visibleTokens} strategy={horizontalListSortingStrategy}>
                    {visibleTokens.map(renderCard)}
                  </SortableContext>
                  {/* Spawn a new side chat to the right of the last panel. */}
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
                {/* Floating "Chat about this" pill for AI-passage selections */}
                <PassageSelectionMenu onChatAboutPassage={handleCreateSubChat} />
              </>
            )}
          </div>
        </DndContext>
      </div>
    </AppShell>
  )
}
