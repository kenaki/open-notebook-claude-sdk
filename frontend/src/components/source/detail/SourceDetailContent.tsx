'use client'

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

interface SourceDetailContentProps {
  sourceId: string
  showChatButton?: boolean
  onChatClick?: () => void
  onClose?: () => void
}

export function SourceDetailContent({
  sourceId,
  showChatButton = false,
  onChatClick,
  onClose
}: SourceDetailContentProps) {
  const { t } = useTranslation()
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
      <div className="pb-4 px-2">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <InlineEdit
              value={source.title || ''}
              onSave={handleUpdateTitle}
              className="text-2xl font-bold"
              inputClassName="text-2xl font-bold"
              placeholder={t('sources.titlePlaceholder')}
              emptyText={t('sources.untitledSource')}
            />
            <p className="mt-1 text-sm text-muted-foreground">
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
      <div className="flex-1 overflow-y-auto px-2">
        <Tabs defaultValue="content" className="w-full">
          <TabsList className="grid w-full grid-cols-3 sticky top-0 z-10">
            <TabsTrigger value="content">{t('sources.content')}</TabsTrigger>
            <TabsTrigger value="insights">
              {t('common.insights')} {insights.length > 0 && `(${insights.length})`}
            </TabsTrigger>
            <TabsTrigger value="details">{t('sources.details')}</TabsTrigger>
          </TabsList>

          <TabsContent value="content" className="mt-6">
            <SourceContentTab source={source} />
          </TabsContent>

          <TabsContent value="insights" className="mt-6">
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
          </TabsContent>

          <TabsContent value="details" className="mt-6">
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
          </TabsContent>
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
