'use client'

import { useState, useEffect, useCallback, useRef, type ReactNode } from 'react'
import { useMutation, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { toast } from 'sonner'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { InlineEdit } from '@/components/common/InlineEdit'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Link as LinkIcon,
  Upload,
  AlignLeft,
  Download,
  MoreVertical,
  Trash2,
  Database,
  MessageSquare,
  RotateCw,
  CircleCheck,
  TriangleAlert,
} from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useSourceDetail } from '@/lib/hooks/useSourceDetail'
import { useParseStatus, SOURCE_BLOCK_KEYS } from '@/lib/hooks/use-source-blocks'
import { useSourceAnnotations } from '@/lib/hooks/use-source-annotations'
import { useAnnotationJumpStore } from '@/lib/stores/annotation-jump-store'
import { sourcesApi } from '@/lib/api/sources'
import { toastApiError } from '@/lib/utils/error-handler'
import { SourceInsightDialog } from './SourceInsightDialog'
import { SourceContentTab } from './SourceContentTab'
import { SourceInsightsTab } from './SourceInsightsTab'
import { SourceDetailsTab } from './SourceDetailsTab'
import { PDFViewer } from '@/components/common/PDFViewer'
import { ReaderView } from '@/components/source/reader/ReaderView'
import { useLastReadPage } from '@/lib/hooks/use-last-read-page'
import type { Annotation, SourceDetailResponse, ParseStatusResponse } from '@/lib/types/api'

// Which tabs the per-source tab preference may restore to (D8). The PDF tab is
// added only for a PDF asset. Persisted under this localStorage prefix.
const TAB_PREF_PREFIX = 'source-detail-tab-'
const BASE_TABS = new Set(['reader', 'insights', 'details'])
// The Content tab folded into Reader; a preference stored before that lands
// would otherwise restore to a tab that no longer exists.
const LEGACY_TAB_ALIASES: Record<string, string> = { content: 'reader' }

/** Returns true when the source's uploaded file is a PDF. */
const isPdfAsset = (source: SourceDetailResponse): boolean =>
  source.asset?.file_path?.toLowerCase().endsWith('.pdf') ?? false

// Parse statuses still in-flight (spinner chip). Terminal states are ready/failed.
const TRANSIENT_PARSE_STATUSES = new Set(['pending', 'parsing', 'embedding'])

/**
 * Block-parse lifecycle chip for the source header (pdf-block-ingestion D4).
 * Driven by `useParseStatus`: a transient status shows a spinner; `ready` shows a
 * tick with a parser/generation tooltip; `failed` shows an alert with the error;
 * a never-parsed source (404 ⇒ `query.isError`) shows a muted "not parsed" hint.
 * Renders nothing until the first fetch resolves (avoids a flash on tab open).
 */
function ParseStatusChip({
  query,
}: {
  query: UseQueryResult<ParseStatusResponse>
}) {
  const { t } = useTranslation()

  const chip = (
    icon: ReactNode,
    label: string,
    tip: string,
    className: string
  ) => (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={`inline-flex items-center gap-1 rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium ${className}`}
        >
          {icon}
          {label}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-56">{tip}</TooltipContent>
    </Tooltip>
  )

  // Never parsed into blocks yet (endpoint 404s) — a muted, actionable hint.
  if (query.isError) {
    return chip(
      null,
      t('sources.parse.statusNotParsed'),
      t('sources.parse.notParsedTip'),
      'text-muted-foreground'
    )
  }

  const status = query.data?.parse_status
  if (!status) return null // first load in flight

  if (TRANSIENT_PARSE_STATUSES.has(status)) {
    const label =
      status === 'pending'
        ? t('sources.parse.statusQueued')
        : status === 'embedding'
          ? t('sources.parse.statusEmbedding')
          : t('sources.parse.statusParsing')
    return chip(
      <LoadingSpinner size="sm" />,
      label,
      t('sources.parse.workingTip'),
      'text-muted-foreground'
    )
  }

  if (status === 'failed') {
    return chip(
      <TriangleAlert className="h-3 w-3" aria-hidden="true" />,
      t('sources.parse.statusFailed'),
      query.data?.error || t('sources.parse.failedTip'),
      'border-destructive/40 text-destructive'
    )
  }

  // ready (or any other terminal status) → parsed.
  const parser = [query.data?.parser_name, query.data?.parser_version]
    .filter(Boolean)
    .join(' ')
  const tip = t('sources.parse.readyTip')
    .replace('{parser}', parser || t('sources.parse.unknownParser'))
    .replace('{gen}', String(query.data?.gen ?? ''))
  return chip(
    <CircleCheck className="h-3 w-3" aria-hidden="true" />,
    t('sources.parse.statusReady'),
    tip,
    'border-emerald-500/40 text-emerald-600 dark:text-emerald-400'
  )
}

interface SourceDetailContentProps {
  sourceId: string
  showChatButton?: boolean
  onChatClick?: () => void
  onClose?: () => void
  /**
   * Decision #20: physical page (1-indexed, from a `[source:id#p=N]` citation).
   * When set on a PDF source, the view jumps to the PDF tab opened at that page.
   */
  initialPage?: number
  /**
   * Phase4: forwarded to PDFViewer's "Chat about this" highlight action.
   * Omit where no chat is wired to this view (e.g. the source modal) — the
   * button hides itself when this is undefined.
   *
   * D8: the optional 2nd arg carries the annotation id (present for an existing
   * highlight; absent for a fresh selection → quote fallback).
   */
  onChatAboutHighlight?: (quote: string, annotationId?: string) => void
  /**
   * Phase4 batch variant: forwarded to PDFViewer for "Ask AI about <tag>".
   * Omit where no chat is wired — the sidebar button hides itself. D8: 3rd arg
   * carries the matching annotation ids for the structured `annotation_ids` send.
   */
  onChatAboutHighlights?: (quotes: string[], tag: string, annotationIds?: string[]) => void
  /**
   * 'stacked' (default) is the modal layout: header block, then a full-width
   * tab bar. 'toolbar' collapses everything into ONE header line — leading
   * slot, editable title, tab triggers, type badge, actions menu, trailing
   * slot — so the tab content (esp. the PDF) gets the rest of the viewport.
   */
  layout?: 'stacked' | 'toolbar'
  /** Toolbar layout only: rendered at the far left (e.g. back button). */
  toolbarLeading?: ReactNode
  /** Toolbar layout only: rendered at the far right (e.g. chat toggle). */
  toolbarTrailing?: ReactNode
}

export function SourceDetailContent({
  sourceId,
  showChatButton = false,
  onChatClick,
  onClose,
  initialPage,
  onChatAboutHighlight,
  onChatAboutHighlights,
  layout = 'stacked',
  toolbarLeading,
  toolbarTrailing
}: SourceDetailContentProps) {
  const { t } = useTranslation()
  // Controlled tab so a page citation can programmatically open the PDF tab.
  const [activeTab, setActiveTab] = useState('reader')
  // Lazy-mount-then-keep-alive: a tab's content mounts on first activation and
  // then stays mounted (hidden via CSS) so switching back is instant — the PDF
  // isn't re-downloaded/re-parsed and the chapter markdown isn't re-rendered.
  const [mountedTabs, setMountedTabs] = useState(() => new Set(['reader']))

  // --- Reader ↔ PDF page sync ----------------------------------------------- //
  // One "last page read" per source. Whichever tab is active reports the page
  // it's on; entering the other tab jumps it there. Because the panels stay
  // mounted, a hidden viewer's page reports are ignored (a hidden PDF's
  // virtualizer can report page 1) — `activeTabRef` is the gate.
  const { storedPage, lastPageRef, recordPage } = useLastReadPage(sourceId)
  const activeTabRef = useRef(activeTab)
  const readerPageRef = useRef<number | null>(null)
  const pdfPageRef = useRef<number | null>(null)
  const readerPageJumpRef = useRef<((page: number) => void) | null>(null)
  const pdfPageJumpRef = useRef<((page: number) => void) | null>(null)
  // Frozen at the PDF tab's first mount: <Viewer> reads `initialPage` once, and
  // the panel is never unmounted afterwards, so every later sync is a jump.
  const pdfOpenPageRef = useRef<number | null>(null)
  const [pendingPageSync, setPendingPageSync] = useState<{
    tab: 'pdf' | 'reader'
    page: number
    nonce: number
  } | null>(null)

  const recordReaderPage = useCallback((page: number) => {
    readerPageRef.current = page
    if (activeTabRef.current === 'reader') recordPage(page)
  }, [recordPage])

  const recordPdfPage = useCallback((page: number) => {
    pdfPageRef.current = page
    if (activeTabRef.current === 'pdf') recordPage(page)
  }, [recordPage])

  // `syncPage: false` for a switch that already carries its own scroll target —
  // an annotation jump or a `#p=N` citation — so page sync can't fight it.
  const handleTabChange = useCallback((tab: string, options?: { syncPage?: boolean }) => {
    const target = lastPageRef.current
    // The first PDF mount opens at `initialPage`; syncing it too would jump a
    // document that hasn't loaded yet.
    const pdfFirstMount = tab === 'pdf' && pdfOpenPageRef.current == null
    if (pdfFirstMount) pdfOpenPageRef.current = initialPage ?? target ?? 1

    setActiveTab(tab)
    activeTabRef.current = tab
    setMountedTabs((prev) => (prev.has(tab) ? prev : new Set(prev).add(tab)))

    const syncPage = (options?.syncPage ?? true) && !pdfFirstMount
    if (syncPage && target != null && (tab === 'pdf' || tab === 'reader')) {
      setPendingPageSync({ tab, page: target, nonce: Date.now() })
    }

    // D8: remember the active tab per source so it survives reload.
    try {
      window.localStorage.setItem(TAB_PREF_PREFIX + sourceId, tab)
    } catch {
      // localStorage unavailable (private mode) — non-persistent is fine.
    }
  }, [sourceId, initialPage, lastPageRef])

  // Applied a frame after the switch: the incoming panel is `display: none`
  // until React commits, and scrollIntoView/jumpToPage no-op on a hidden node.
  useEffect(() => {
    if (!pendingPageSync) return
    const { tab, page } = pendingPageSync
    const raf = requestAnimationFrame(() => {
      const currentPage = tab === 'reader' ? readerPageRef.current : pdfPageRef.current
      if (currentPage === page) return
      const jump = tab === 'reader' ? readerPageJumpRef.current : pdfPageJumpRef.current
      jump?.(page)
    })
    return () => cancelAnimationFrame(raf)
  }, [pendingPageSync])

  const {
    source,
    insights,
    transformations,
    selectedTransformation,
    setSelectedTransformation,
    loading,
    loadingInsights,
    creatingInsight,
    error,
    copied,
    isEmbedding,
    isDownloadingFile,
    fileAvailable,
    selectedInsight,
    setSelectedInsight,
    insightToDelete,
    setInsightToDelete,
    deletingInsight,
    fetchSource,
    createInsight,
    handleDeleteInsight,
    handleDeleteSelectedInsight,
    handleUpdateTitle,
    handleEmbedContent,
    handleDownloadFile,
    handleCopyUrl,
    handleOpenExternal,
    handleDelete,
  } = useSourceDetail({ sourceId, onClose })

  const queryClient = useQueryClient()
  const [reparseOpen, setReparseOpen] = useState(false)
  // Only PDFs carry a block-parse lifecycle; disable the poll for other sources.
  const isPdf = source ? isPdfAsset(source) : false
  const parseStatus = useParseStatus(isPdf ? sourceId : undefined)
  // The Reader tab renders the block substrate only once it's parsed for this
  // source's current generation; otherwise (non-PDF, unparsed, failed parse) it
  // falls back to the regenerated markdown. `parseSettled` keeps it from
  // flashing the fallback while the status poll is still in flight.
  const readerReady = isPdf && parseStatus.isSuccess
  const parseSettled = !isPdf || parseStatus.isSuccess || parseStatus.isError
  const reparseMutation = useMutation({
    mutationFn: () => sourcesApi.reparse(sourceId),
    onSuccess: () => {
      toast.success(t('sources.parse.reprocessQueued'))
      // Refetch the status header so the chip flips into its (polling) transient
      // state as the worker starts writing the new generation.
      queryClient.invalidateQueries({ queryKey: SOURCE_BLOCK_KEYS.parse(sourceId) })
      setReparseOpen(false)
    },
    onError: (err: unknown) => {
      toastApiError(err, t, 'sources.parse.reprocessFailed')
      setReparseOpen(false)
    },
  })

  // --- D8: reader ↔ sidebar/chat jump parity -------------------------------- //
  // Full annotation list (needed to resolve a pill's id → rect/anchor for the
  // jump). Only PDFs carry annotations; the query is cheap/empty otherwise.
  const { data: annotations = [] } = useSourceAnnotations(isPdf ? sourceId : undefined)
  // Imperative handles the child viewers fill in (PDF: jump-to-rect; Reader:
  // scroll-to-seq). Populated only while the respective tab is mounted.
  const pdfJumpRef = useRef<((annotation: Annotation) => void) | null>(null)
  const readerJumpRef = useRef<((seq: number) => void) | null>(null)
  // A pending jump is applied one frame after a possible tab switch, so a
  // newly-mounted viewer has committed its imperative handle first.
  const [pendingJump, setPendingJump] = useState<{
    annotation: Annotation
    tab: 'pdf' | 'reader'
    nonce: number
  } | null>(null)

  const registerJump = useAnnotationJumpStore((s) => s.register)
  const unregisterJump = useAnnotationJumpStore((s) => s.unregister)

  // Route a jump by the ACTIVE tab: anchored + reader tab → scroll the reader;
  // otherwise → the PDF tab (jumpToHighlightArea). A legacy highlight (no block
  // anchor) can't render in the reader, so it always jumps on the PDF tab,
  // auto-switching with a toast.
  const routeJump = useCallback(
    (annotationId: string) => {
      const annotation = annotations.find((a) => a.id === annotationId)
      if (!annotation) return
      const hasAnchor = annotation.block_seq != null
      const goReader = hasAnchor && activeTab === 'reader'
      if (!hasAnchor && activeTab === 'reader') {
        toast.info(t('sources.annotations.jumpLegacyPdf'))
      }
      const tab: 'pdf' | 'reader' = goReader ? 'reader' : 'pdf'
      if (activeTab !== tab) handleTabChange(tab, { syncPage: false })
      setPendingJump({ annotation, tab, nonce: Date.now() })
    },
    [annotations, activeTab, handleTabChange, t]
  )

  useEffect(() => {
    if (!pendingJump) return
    const raf = requestAnimationFrame(() => {
      if (pendingJump.tab === 'reader') {
        if (pendingJump.annotation.block_seq != null) {
          readerJumpRef.current?.(pendingJump.annotation.block_seq)
        }
      } else {
        pdfJumpRef.current?.(pendingJump.annotation)
      }
    })
    return () => cancelAnimationFrame(raf)
  }, [pendingJump])

  // Expose the router to the chat pills (rendered in a sibling subtree).
  useEffect(() => {
    if (!sourceId) return
    registerJump(sourceId, routeJump)
    return () => unregisterJump(sourceId)
  }, [sourceId, routeJump, registerJump, unregisterJump])

  // D8: restore the persisted tab once the source (and, for PDFs, its parse
  // status) has settled — so a reload lands back where the user left off. Runs
  // once; a `#p=N` citation deep-link (initialPage) wins over the stored tab.
  const restoredRef = useRef(false)
  useEffect(() => {
    if (restoredRef.current || !source) return
    if (initialPage != null) {
      restoredRef.current = true
      return
    }
    if (!parseSettled) return
    restoredRef.current = true
    try {
      const stored = window.localStorage.getItem(TAB_PREF_PREFIX + sourceId)
      if (!stored) return
      const tab = LEGACY_TAB_ALIASES[stored] ?? stored
      const valid = new Set(BASE_TABS)
      if (isPdf) valid.add('pdf')
      // Each viewer restores its own page on mount, so no sync on this switch.
      if (valid.has(tab)) handleTabChange(tab, { syncPage: false })
    } catch {
      // localStorage unavailable — keep the default tab.
    }
  }, [source, isPdf, initialPage, sourceId, parseSettled, handleTabChange])

  // Header controls for PDF sources: the parse-lifecycle chip + a Re-process
  // action (confirm-gated). Hidden entirely for non-PDF sources.
  const parseStatusControls = isPdf ? (
    <div className="flex items-center gap-1.5">
      <ParseStatusChip query={parseStatus} />
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => setReparseOpen(true)}
            disabled={reparseMutation.isPending}
            aria-label={t('sources.parse.reprocess')}
          >
            <RotateCw className="h-3.5 w-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t('sources.parse.reprocess')}</TooltipContent>
      </Tooltip>
    </div>
  ) : null

  // Decision #20: when opened via a `#p=N` citation on a PDF source, jump to the
  // PDF tab (the PDFViewer itself opens at the page). Runs once the source loads.
  useEffect(() => {
    if (initialPage != null && source && isPdfAsset(source)) {
      handleTabChange('pdf', { syncPage: false })
    }
  }, [initialPage, source, handleTabChange])

  const getSourceIcon = () => {
    if (!source) return null
    if (source.asset?.url) return <LinkIcon className="h-5 w-5" />
    if (source.asset?.file_path) return <Upload className="h-5 w-5" />
    return <AlignLeft className="h-5 w-5" />
  }

  const getSourceType = () => {
    if (!source) return 'unknown'
    if (source.asset?.url) return 'link'
    if (source.asset?.file_path) return 'file'
    return 'text'
  }

  // Toolbar layout keeps its leading slot (the back button) reachable even
  // while the source is loading or failed to load.
  const toolbarShell = (body: ReactNode) => (
    <div className="flex h-full flex-col">
      {layout === 'toolbar' && toolbarLeading && (
        <div className="flex flex-shrink-0 items-center gap-3 border-b border-border px-4 py-2">
          {toolbarLeading}
        </div>
      )}
      {body}
    </div>
  )

  if (loading) {
    return toolbarShell(
      <div className="flex flex-1 items-center justify-center p-8">
        <LoadingSpinner />
      </div>
    )
  }

  if (error || !source) {
    return toolbarShell(
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
        <p className="text-red-500">{error || t('sources.notFound')}</p>
      </div>
    )
  }

  const actionsMenu = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon">
          <MoreVertical className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {source.asset?.file_path && (
          <>
            <DropdownMenuItem
              onClick={handleDownloadFile}
              disabled={isDownloadingFile || fileAvailable === false}
            >
              <Download className="mr-2 h-4 w-4" />
              {fileAvailable === false
                ? t('sources.fileUnavailable')
                : isDownloadingFile
                  ? t('sources.preparing')
                  : t('sources.downloadFile')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
          </>
        )}
        <DropdownMenuItem
          onClick={handleEmbedContent}
          disabled={isEmbedding || source.embedded}
        >
          <Database className="mr-2 h-4 w-4" />
          {isEmbedding ? t('sources.embedding') : source.embedded ? t('sources.alreadyEmbedded') : t('sources.embedContent')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          className="text-destructive"
          onClick={handleDelete}
        >
          <Trash2 className="mr-2 h-4 w-4" />
          {t('sources.deleteSource')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )

  // Reader leads and is never disabled — it falls back to the regenerated
  // markdown when there's no block substrate to render.
  const tabTriggers = (
    <>
      <TabsTrigger value="reader">{t('sources.reader.tab')}</TabsTrigger>
      {isPdfAsset(source) && (
        <TabsTrigger value="pdf">{t('sources.viewPdf')}</TabsTrigger>
      )}
      <TabsTrigger value="insights">
        {t('common.insights')} {insights.length > 0 && `(${insights.length})`}
      </TabsTrigger>
      <TabsTrigger value="details">{t('sources.details')}</TabsTrigger>
    </>
  )

  // forceMount + data-[state=inactive]:hidden keeps visited panels alive
  // across switches; mountedTabs defers each panel's first mount until its
  // tab is opened.
  const tabPanels = (
    <>
      {/* ReaderView scrolls its own block list; the markdown fallback is a plain
          Card and needs this panel to be the scroller. */}
      <TabsContent
        value="reader"
        forceMount
        className={`mt-3 flex min-h-0 flex-1 flex-col data-[state=inactive]:hidden ${
          readerReady ? '' : 'overflow-y-auto'
        }`}
      >
        {mountedTabs.has('reader') &&
          (!parseSettled ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <LoadingSpinner />
            </div>
          ) : readerReady ? (
            <ReaderView
              sourceId={source.id}
              onChatAboutHighlight={onChatAboutHighlight}
              onChatAboutHighlights={onChatAboutHighlights}
              onJumpToAnnotation={routeJump}
              onReprocess={() => setReparseOpen(true)}
              jumpApiRef={readerJumpRef}
              initialPage={storedPage}
              onPageChange={recordReaderPage}
              pageJumpApiRef={readerPageJumpRef}
            />
          ) : (
            // No block substrate (URL, transcript, unparsed or failed PDF) —
            // render the regenerated markdown instead.
            <SourceContentTab source={source} title={t('sources.reader.tab')} />
          ))}
      </TabsContent>

      <TabsContent value="insights" forceMount className="mt-3 min-h-0 flex-1 overflow-y-auto data-[state=inactive]:hidden">
        {mountedTabs.has('insights') && (
          <SourceInsightsTab
            insights={insights}
            loadingInsights={loadingInsights}
            transformations={transformations}
            selectedTransformation={selectedTransformation}
            onSelectTransformation={setSelectedTransformation}
            creatingInsight={creatingInsight}
            onCreateInsight={createInsight}
            onViewInsight={setSelectedInsight}
            onDeleteInsight={setInsightToDelete}
          />
        )}
      </TabsContent>

      <TabsContent value="details" forceMount className="mt-3 min-h-0 flex-1 overflow-y-auto data-[state=inactive]:hidden">
        {mountedTabs.has('details') && (
          <SourceDetailsTab
            source={source}
            sourceId={sourceId}
            isEmbedding={isEmbedding}
            onEmbedContent={handleEmbedContent}
            copied={copied}
            onCopyUrl={handleCopyUrl}
            onOpenExternal={handleOpenExternal}
            isDownloadingFile={isDownloadingFile}
            fileAvailable={fileAvailable}
            onDownloadFile={handleDownloadFile}
            onAssociationsSave={fetchSource}
          />
        )}
      </TabsContent>

      {isPdfAsset(source) && (
        <TabsContent value="pdf" forceMount className="mt-3 flex min-h-0 flex-1 flex-col data-[state=inactive]:hidden">
          {/* The viewer's initialPage is 0-based; both sources here are 1-indexed
              physical pages. A `#p=N` citation wins — `key` remounts the viewer
              when it changes, and pdfOpenPageRef stays frozen at the page the
              tab first opened on. key must NOT track the synced page: that would
              remount (and re-lay-out) pdf.js on every tab switch. */}
          {mountedTabs.has('pdf') && (
            <PDFViewer
              key={`pdf-${initialPage ?? 'first'}`}
              sourceId={source.id}
              initialPage={Math.max(0, (initialPage ?? pdfOpenPageRef.current ?? 1) - 1)}
              onChatAboutHighlight={onChatAboutHighlight}
              onChatAboutHighlights={onChatAboutHighlights}
              jumpApiRef={pdfJumpRef}
              onPageChange={recordPdfPage}
              pageJumpApiRef={pdfPageJumpRef}
            />
          )}
        </TabsContent>
      )}
    </>
  )

  const dialogs = (
    <>
      <SourceInsightDialog
        open={Boolean(selectedInsight)}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedInsight(null)
          }
        }}
        insight={selectedInsight ?? undefined}
        onDelete={handleDeleteSelectedInsight}
      />

      <ConfirmDialog
        open={!!insightToDelete}
        onOpenChange={(open) => {
          if (!open) {
            setInsightToDelete(null)
          }
        }}
        title={t('sources.deleteInsight')}
        description={t('sources.deleteInsightConfirm')}
        confirmText={t('common.delete')}
        confirmVariant="destructive"
        onConfirm={handleDeleteInsight}
        isLoading={deletingInsight}
      />

      <ConfirmDialog
        open={reparseOpen}
        onOpenChange={(open) => {
          if (!open && !reparseMutation.isPending) setReparseOpen(false)
        }}
        title={t('sources.parse.reprocessTitle')}
        description={t('sources.parse.reprocessConfirm')}
        confirmText={t('sources.parse.reprocess')}
        onConfirm={() => reparseMutation.mutate()}
        isLoading={reparseMutation.isPending}
      />
    </>
  )

  // Toolbar layout (full-page route): everything in ONE header line so the
  // active tab — especially the PDF — gets the rest of the viewport.
  if (layout === 'toolbar') {
    return (
      <div className="flex flex-col h-full">
        <Tabs value={activeTab} onValueChange={handleTabChange} className="flex min-h-0 w-full flex-1 flex-col">
          <div className="flex flex-shrink-0 items-center gap-3 border-b border-border px-4 py-2">
            {toolbarLeading}
            <div className="min-w-0 flex-1">
              <InlineEdit
                value={source.title || ''}
                onSave={handleUpdateTitle}
                className="truncate text-sm font-semibold"
                inputClassName="text-sm font-semibold"
                placeholder={t('sources.titlePlaceholder')}
                emptyText={t('sources.untitledSource')}
              />
            </div>
            <TabsList className="flex-shrink-0">{tabTriggers}</TabsList>
            <div className="flex flex-shrink-0 items-center gap-2">
              {parseStatusControls}
              <Badge variant="secondary" className="text-xs">
                {getSourceType()}
              </Badge>
              {actionsMenu}
              {toolbarTrailing}
            </div>
          </div>
          <div className="flex min-h-0 flex-1 flex-col px-4 pb-3">
            {tabPanels}
          </div>
        </Tabs>
        {dialogs}
      </div>
    )
  }

  // Stacked layout (source modal): header block, then a full-width tab bar.
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className={`px-2 pb-2 ${showChatButton ? 'pr-12' : ''}`}>
        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <InlineEdit
              value={source.title || ''}
              onSave={handleUpdateTitle}
              className="text-lg font-bold"
              inputClassName="text-lg font-bold"
              placeholder={t('sources.titlePlaceholder')}
              emptyText={t('sources.untitledSource')}
            />
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {t('sources.id')}: {source.id}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {parseStatusControls}
            {getSourceIcon()}
            <Badge variant="secondary" className="text-sm">
              {getSourceType()}
            </Badge>

            {/* Chat with source button - only in modal */}
            {showChatButton && onChatClick && (
              <Button variant="outline" size="sm" onClick={onChatClick}>
                <MessageSquare className="h-4 w-4 mr-2" />
                {t('chat.chatWith').replace('{name}', t('navigation.sources'))}
              </Button>
            )}

            {actionsMenu}
          </div>
        </div>
      </div>

      {/* Tabs Content */}
      <div className="flex min-h-0 flex-1 flex-col px-2">
        <Tabs value={activeTab} onValueChange={handleTabChange} className="flex min-h-0 w-full flex-1 flex-col">
          <TabsList className={`grid w-full ${isPdfAsset(source) ? 'grid-cols-4' : 'grid-cols-3'} flex-shrink-0`}>
            {tabTriggers}
          </TabsList>
          {tabPanels}
        </Tabs>
      </div>

      {dialogs}
    </div>
  )
}
