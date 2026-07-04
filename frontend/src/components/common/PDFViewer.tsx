'use client'

// NOTE: @react-pdf-viewer/core requires pdfjs-dist ^3.x and has a peer-dep
// of react >=16.8.0 <19.0.0. This project uses React 19 — install with
// --legacy-peer-deps at integration. If runtime breakage occurs, fall back
// to `react-pdf` + a custom page-navigation layer (see coordinator Decision #13).
import { Worker, Viewer } from '@react-pdf-viewer/core'
import { defaultLayoutPlugin } from '@react-pdf-viewer/default-layout'
import {
  highlightPlugin,
  Trigger,
  type RenderHighlightTargetProps,
  type RenderHighlightsProps,
} from '@react-pdf-viewer/highlight'
import '@react-pdf-viewer/core/lib/styles/index.css'
import '@react-pdf-viewer/default-layout/lib/styles/index.css'
import '@react-pdf-viewer/highlight/lib/styles/index.css'
import { sourcesApi } from '@/lib/api/sources'
import { memo, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from '@/lib/hooks/use-translation'
import {
  useSourceAnnotations,
  useCreateAnnotation,
  useDeleteAnnotation,
  useUpdateAnnotation,
} from '@/lib/hooks/use-source-annotations'
import { AnnotationsSidebar } from '@/components/source/detail/AnnotationsSidebar'
import {
  AnnotationHighlightPopover,
  HIGHLIGHT_COLORS,
} from '@/components/source/detail/AnnotationHighlightPopover'
import type { Annotation } from '@/lib/types/api'

// Worker is served from public/pdf.worker.min.js (copied from
// node_modules/pdfjs-dist/build) so PDF viewing works offline/self-hosted.
// Keep the copy in sync with the pdfjs-dist version pinned in package.json.
const PDFJS_WORKER_URL = '/pdf.worker.min.js'

interface PDFViewerProps {
  sourceId: string
  /**
   * 0-based page index to open initially.
   * Phase3 will pass the citation page number here — prop is pre-wired
   * so Phase3 needs no PDFViewer changes.
   */
  initialPage?: number
  /**
   * Document Foundation Phase4: called with the selected highlight's quote
   * when the user clicks "Chat about this" on an existing highlight. Reuses
   * the PassageSelectionMenu ACTION (send the quote to the active chat), not
   * the component itself — that pill is scoped to chat-bubble selections via
   * `data-chat-scope` and doesn't apply inside the PDF text layer. Callers
   * with no wired chat (e.g. the source modal) omit this — the button hides.
   */
  onChatAboutHighlight?: (quote: string) => void
}

// memo: the parent's tab-switch state changes must not re-render the viewer —
// each re-render creates a fresh defaultLayoutPlugin and re-runs pdf.js layout,
// which costs seconds on a large book. Props are a string, a number and a
// stable callback, so the shallow compare is exact.
export const PDFViewer = memo(function PDFViewer({
  sourceId,
  initialPage = 0,
  onChatAboutHighlight,
}: PDFViewerProps) {
  const { t } = useTranslation()
  const layoutPlugin = defaultLayoutPlugin()

  const { data: annotations = [] } = useSourceAnnotations(sourceId)
  const createAnnotation = useCreateAnnotation(sourceId)
  const updateAnnotation = useUpdateAnnotation(sourceId)
  const deleteAnnotation = useDeleteAnnotation(sourceId)

  // Which EXISTING highlight's popover is open (click position is where the
  // user clicked the overlay, so the popover appears right under the cursor).
  const [activeAnnotation, setActiveAnnotation] = useState<{
    annotation: Annotation
    top: number
    left: number
  } | null>(null)

  // renderHighlightTarget/renderHighlights close over `annotations` and the
  // mutation functions below — recreated every render alongside layoutPlugin
  // (see comment above), so they never see stale data. `highlightPlugin`
  // itself is a plain factory (no internal React state keyed off identity),
  // matching how `defaultLayoutPlugin()` is already used unmemoized here.
  const renderHighlightTarget = (props: RenderHighlightTargetProps) => (
    <div
      style={{
        position: 'absolute',
        left: `${props.selectionRegion.left}%`,
        top: `${props.selectionRegion.top + props.selectionRegion.height}%`,
        transform: 'translateY(4px)',
        zIndex: 50,
      }}
    >
      <button
        type="button"
        className="rounded-md border border-border bg-popover px-2 py-1 text-xs font-medium text-popover-foreground shadow-[var(--shadow)] hover:bg-muted"
        onClick={() => {
          createAnnotation.mutate({
            page: props.selectionRegion.pageIndex + 1,
            rect: props.highlightAreas,
            color: HIGHLIGHT_COLORS[0],
            quote: props.selectedText,
          })
          props.cancel()
        }}
      >
        {t('sources.annotations.addHighlight')}
      </button>
    </div>
  )

  const renderHighlights = (props: RenderHighlightsProps) => (
    <div>
      {annotations.map((annotation) =>
        annotation.rect
          .filter((area) => area.pageIndex === props.pageIndex)
          .map((area, idx) => (
            <div
              key={`${annotation.id}-${idx}`}
              onClick={(e) => {
                e.stopPropagation()
                setActiveAnnotation({ annotation, top: e.clientY, left: e.clientX })
              }}
              style={{
                ...props.getCssProperties(area, props.rotation),
                background: annotation.color,
                opacity: 0.4,
                cursor: 'pointer',
              }}
            />
          ))
      )}
    </div>
  )

  const highlightPluginInstance = highlightPlugin({
    trigger: Trigger.TextSelection,
    renderHighlightTarget,
    renderHighlights,
  })

  // The blob lives in the TanStack cache under a root key deliberately OUTSIDE
  // the ['sources'] tree: source mutations broadly invalidate ['sources'], and
  // that must never re-download a multi-MB file. The uploaded asset is
  // immutable, so staleTime: Infinity is safe. Errors surface inline below
  // (meta.silent opts out of the global query-error toast).
  const { data: pdfBlob, error } = useQuery({
    queryKey: ['source-file', sourceId],
    queryFn: async () => (await sourcesApi.downloadFile(sourceId)).data,
    staleTime: Infinity,
    meta: { silent: true },
  })

  // Fresh object URL per mount from the cached blob; revoked on unmount.
  const pdfUrl = useMemo(
    () => (pdfBlob ? URL.createObjectURL(pdfBlob) : null),
    [pdfBlob]
  )
  useEffect(() => {
    return () => {
      if (pdfUrl) URL.revokeObjectURL(pdfUrl)
    }
  }, [pdfUrl])

  if (error) {
    return (
      <div className="flex items-center justify-center p-8 text-destructive">
        {error instanceof Error ? error.message : String(error)}
      </div>
    )
  }

  if (!pdfUrl) {
    return (
      <div className="flex items-center justify-center p-8 text-muted-foreground">
        {t('sources.loadingPdf')}
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 gap-2">
      <Worker workerUrl={PDFJS_WORKER_URL}>
        <div className="min-h-0 flex-1">
          <Viewer
            fileUrl={pdfUrl}
            plugins={[layoutPlugin, highlightPluginInstance]}
            initialPage={initialPage}
          />
        </div>
      </Worker>

      <AnnotationsSidebar
        annotations={annotations}
        onJumpTo={(annotation) => {
          const area = annotation.rect[0]
          if (area) highlightPluginInstance.jumpToHighlightArea(area)
        }}
      />

      {activeAnnotation && (
        <AnnotationHighlightPopover
          annotation={activeAnnotation.annotation}
          top={activeAnnotation.top}
          left={activeAnnotation.left}
          onClose={() => setActiveAnnotation(null)}
          onSaveNote={(note) => {
            updateAnnotation.mutate({ id: activeAnnotation.annotation.id, data: { note } })
            setActiveAnnotation(null)
          }}
          onChangeColor={(color) => {
            updateAnnotation.mutate({ id: activeAnnotation.annotation.id, data: { color } })
            setActiveAnnotation((prev) =>
              prev ? { ...prev, annotation: { ...prev.annotation, color } } : prev
            )
          }}
          onDelete={() => {
            deleteAnnotation.mutate(activeAnnotation.annotation.id)
            setActiveAnnotation(null)
          }}
          onChatAboutHighlight={
            onChatAboutHighlight
              ? (quote) => {
                  onChatAboutHighlight(quote)
                  setActiveAnnotation(null)
                }
              : undefined
          }
        />
      )}
    </div>
  )
})
