'use client'

import { useState, useEffect, useCallback } from 'react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { InlineEdit } from '@/components/common/InlineEdit'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
} from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useSourceDetail } from '@/lib/hooks/useSourceDetail'
import { SourceInsightDialog } from './SourceInsightDialog'
import { SourceContentTab } from './SourceContentTab'
import { SourceInsightsTab } from './SourceInsightsTab'
import { SourceDetailsTab } from './SourceDetailsTab'
import { PDFViewer } from '@/components/common/PDFViewer'
import type { SourceDetailResponse } from '@/lib/types/api'

/** Returns true when the source's uploaded file is a PDF. */
const isPdfAsset = (source: SourceDetailResponse): boolean =>
  source.asset?.file_path?.toLowerCase().endsWith('.pdf') ?? false

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
   */
  onChatAboutHighlight?: (quote: string) => void
}

export function SourceDetailContent({
  sourceId,
  showChatButton = false,
  onChatClick,
  onClose,
  initialPage,
  onChatAboutHighlight
}: SourceDetailContentProps) {
  const { t } = useTranslation()
  // Controlled tab so a page citation can programmatically open the PDF tab.
  const [activeTab, setActiveTab] = useState('content')
  // Lazy-mount-then-keep-alive: a tab's content mounts on first activation and
  // then stays mounted (hidden via CSS) so switching back is instant — the PDF
  // isn't re-downloaded/re-parsed and the chapter markdown isn't re-rendered.
  const [mountedTabs, setMountedTabs] = useState(() => new Set(['content']))
  const handleTabChange = useCallback((tab: string) => {
    setActiveTab(tab)
    setMountedTabs((prev) => (prev.has(tab) ? prev : new Set(prev).add(tab)))
  }, [])
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

  // Decision #20: when opened via a `#p=N` citation on a PDF source, jump to the
  // PDF tab (the PDFViewer itself opens at the page). Runs once the source loads.
  useEffect(() => {
    if (initialPage != null && source && isPdfAsset(source)) {
      handleTabChange('pdf')
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

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <LoadingSpinner />
      </div>
    )
  }

  if (error || !source) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
        <p className="text-red-500">{error || t('sources.notFound')}</p>
      </div>
    )
  }

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
          </div>
        </div>
      </div>

      {/* Tabs Content */}
      <div className="flex min-h-0 flex-1 flex-col px-2">
        <Tabs value={activeTab} onValueChange={handleTabChange} className="flex min-h-0 w-full flex-1 flex-col">
          <TabsList className={`grid w-full ${isPdfAsset(source) ? 'grid-cols-4' : 'grid-cols-3'} flex-shrink-0`}>
            <TabsTrigger value="content">{t('sources.content')}</TabsTrigger>
            <TabsTrigger value="insights">
              {t('common.insights')} {insights.length > 0 && `(${insights.length})`}
            </TabsTrigger>
            <TabsTrigger value="details">{t('sources.details')}</TabsTrigger>
            {isPdfAsset(source) && (
              <TabsTrigger value="pdf">{t('sources.viewPdf')}</TabsTrigger>
            )}
          </TabsList>

          {/* forceMount + data-[state=inactive]:hidden keeps visited panels
              alive across switches; mountedTabs defers each panel's first
              mount until its tab is opened. */}
          <TabsContent value="content" forceMount className="mt-3 min-h-0 flex-1 overflow-y-auto data-[state=inactive]:hidden">
            {mountedTabs.has('content') && <SourceContentTab source={source} />}
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
              {/* initialPage is 0-based; the citation page is 1-indexed physical.
                  key remounts the viewer when the cited page changes. */}
              {mountedTabs.has('pdf') && (
                <PDFViewer
                  key={`pdf-${initialPage ?? 'first'}`}
                  sourceId={source.id}
                  initialPage={initialPage != null ? Math.max(0, initialPage - 1) : undefined}
                  onChatAboutHighlight={onChatAboutHighlight}
                />
              )}
            </TabsContent>
          )}
        </Tabs>
      </div>

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
    </div>
  )
}
