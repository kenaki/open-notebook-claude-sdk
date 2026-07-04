'use client'

import { useTranslation } from '@/lib/hooks/use-translation'
import type { Annotation } from '@/lib/types/api'

interface AnnotationsSidebarProps {
  annotations: Annotation[]
  onJumpTo: (annotation: Annotation) => void
}

/**
 * Document Foundation Phase4: compact list of a PDF source's saved
 * highlights, sitting beside the PDFViewer. Purely presentational — jumping
 * is delegated to the caller (which owns the highlight plugin instance).
 */
export function AnnotationsSidebar({ annotations, onJumpTo }: AnnotationsSidebarProps) {
  const { t } = useTranslation()

  return (
    <div className="flex w-56 shrink-0 flex-col overflow-hidden rounded-md border border-border">
      <div className="border-b border-border px-2 py-1.5 text-xs font-semibold text-muted-foreground">
        {t('sources.annotations.title')}
        {annotations.length > 0 && ` (${annotations.length})`}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {annotations.length === 0 ? (
          <p className="p-2 text-xs text-muted-foreground">{t('sources.annotations.emptyState')}</p>
        ) : (
          annotations.map((annotation) => (
            <button
              key={annotation.id}
              type="button"
              onClick={() => onJumpTo(annotation)}
              className="flex w-full items-start gap-1.5 rounded-sm p-1.5 text-left text-xs hover:bg-muted"
            >
              <span
                className="mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: annotation.color }}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-muted-foreground">
                  {t('sources.annotations.pageLabel').replace('{page}', String(annotation.page))}
                </span>
                <span className="line-clamp-2 block">{annotation.note || annotation.quote || ''}</span>
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
