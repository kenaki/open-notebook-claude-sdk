'use client'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  ExternalLink,
  Download,
  Copy,
  CheckCircle,
  Database,
  AlertCircle,
} from 'lucide-react'
import { formatRelative } from '@/lib/utils/format'
import { useTranslation } from '@/lib/hooks/use-translation'
import { SourceDetailResponse } from '@/lib/types/api'
import { NotebookAssociations } from './NotebookAssociations'
import { SourceRawContentDialog } from './SourceRawContentDialog'

interface SourceDetailsTabProps {
  source: SourceDetailResponse
  sourceId: string
  isEmbedding: boolean
  onEmbedContent: () => void
  copied: boolean
  onCopyUrl: () => void
  onOpenExternal: () => void
  isDownloadingFile: boolean
  fileAvailable: boolean | null
  onDownloadFile: () => void
  onAssociationsSave: () => void
}

export function SourceDetailsTab({
  source,
  sourceId,
  isEmbedding,
  onEmbedContent,
  copied,
  onCopyUrl,
  onOpenExternal,
  isDownloadingFile,
  fileAvailable,
  onDownloadFile,
  onAssociationsSave,
}: SourceDetailsTabProps) {
  const { t, language } = useTranslation()

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <CardTitle>{t('sources.details')}</CardTitle>
            <SourceRawContentDialog sourceId={sourceId} />
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Embedding Alert */}
          {!source.embedded && (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>
                {t('sources.notEmbeddedAlert')}
              </AlertTitle>
              <AlertDescription>
                {t('sources.notEmbeddedDesc')}
                <div className="mt-3">
                  <Button
                    onClick={onEmbedContent}
                    disabled={isEmbedding}
                    size="sm"
                  >
                    <Database className="mr-2 h-4 w-4" />
                    {isEmbedding ? t('sources.embedding') : t('sources.embedContent')}
                  </Button>
                </div>
              </AlertDescription>
            </Alert>
          )}

          {/* Source Information */}
          <div className="space-y-4">
            {source.asset?.url && (
              <div>
                <h3 className="mb-2 text-sm font-semibold">{t('common.url')}</h3>
                <div className="flex items-center gap-2">
                  <code className="flex-1 rounded bg-muted px-2 py-1 text-sm">
                    {source.asset.url}
                  </code>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={onCopyUrl}
                  >
                    {copied ? (
                      <CheckCircle className="h-4 w-4" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={onOpenExternal}
                  >
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}

            {source.asset?.file_path && (
              <div className="space-y-2">
                <h3 className="text-sm font-semibold">{t('sources.uploadedFile')}</h3>
                <div className="flex flex-wrap items-center gap-2">
                  <code className="rounded bg-muted px-2 py-1 text-sm">
                    {source.asset.file_path}
                  </code>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={onDownloadFile}
                    disabled={isDownloadingFile || fileAvailable === false}
                  >
                    <Download className="mr-2 h-4 w-4" />
                    {fileAvailable === false
                      ? t('sources.fileUnavailable')
                      : isDownloadingFile
                        ? t('sources.preparing')
                        : t('common.download')}
                  </Button>
                </div>
                {fileAvailable === false ? (
                  <p className="text-xs text-muted-foreground">
                    {t('sources.fileUnavailableDesc')}
                  </p>
                ) : null}
              </div>
            )}

            {source.topics && source.topics.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-semibold">{t('sources.topics')}</h3>
                <div className="flex flex-wrap gap-2">
                  {source.topics.map((topic, idx) => (
                    <Badge key={idx} variant="outline">
                      {topic}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Metadata */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">{t('sources.metadata')}</h3>
              <div className="flex items-center gap-2">
                <Database className="h-3.5 w-3.5 text-muted-foreground" />
                <Badge variant={source.embedded ? "default" : "secondary"} className="text-xs">
                  {source.embedded ? t('sources.embedded') : t('sources.notEmbedded')}
                </Badge>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="text-xs font-medium text-muted-foreground">{t('common.created_label')}</p>
                <p className="text-sm">
                  {formatRelative(source.created, language)}
                </p>
                <p className="text-xs text-muted-foreground">
                  {new Date(source.created).toLocaleString()}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground">{t('common.updated_label')}</p>
                <p className="text-sm">
                  {formatRelative(source.updated, language)}
                </p>
                <p className="text-xs text-muted-foreground">
                  {new Date(source.updated).toLocaleString()}
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Notebook Associations */}
      <NotebookAssociations
        sourceId={sourceId}
        currentNotebookIds={source.notebooks || []}
        onSave={onAssociationsSave}
      />
    </>
  )
}
