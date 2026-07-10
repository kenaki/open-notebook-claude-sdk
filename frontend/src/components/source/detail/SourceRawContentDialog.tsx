'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useTranslation } from '@/lib/hooks/use-translation'
import { sourcesApi } from '@/lib/api/sources'

/**
 * The source's extracted text, unrendered — the same `full_text` the AI reads
 * for chat context and embeddings. Lives in the Details tab as an inspection
 * affordance now that the Reader tab owns the presentable view of the content.
 *
 * Fetched only once the dialog opens, under the query key SourceContentTab
 * already uses, so a source that rendered its markdown fallback serves this
 * from cache.
 */
export function SourceRawContentDialog({ sourceId }: { sourceId: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['sources', sourceId, 'full-text'],
    queryFn: () => sourcesApi.getFullText(sourceId),
    enabled: open,
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <FileText className="mr-2 h-4 w-4" />
          {t('sources.rawContent.open')}
        </Button>
      </DialogTrigger>
      <DialogContent className="flex max-h-[80vh] max-w-3xl flex-col">
        <DialogHeader>
          <DialogTitle>{t('sources.rawContent.title')}</DialogTitle>
          <DialogDescription>{t('sources.rawContent.description')}</DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <div className="flex flex-1 items-center justify-center p-8">
            <LoadingSpinner />
          </div>
        ) : (
          <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words rounded border border-border bg-muted/40 p-3 text-xs leading-5">
            {data?.full_text || t('sources.noContent')}
          </pre>
        )}
      </DialogContent>
    </Dialog>
  )
}
