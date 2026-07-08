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
import { Sparkles, StickyNote } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import {
  useSourceAnnotations,
  useCreateAnnotation,
  useDeleteAnnotation,
  useUpdateAnnotation,
} from '@/lib/hooks/use-source-annotations'
import {
  useParseStatus,
  usePageBlocks,
  selectedBlockSeq,
} from '@/lib/hooks/use-source-blocks'
import { AnnotationsSidebar } from '@/components/source/detail/AnnotationsSidebar'
import {
  AnnotationHighlightPopover,
  ColorDots,
  DEFAULT_HIGHLIGHT_COLOR,
  HIGHLIGHT_PALETTE,
} from '@/components/source/detail/AnnotationHighlightPopover'
import type { Annotation } from '@/lib/types/api'

// Worker is served from public/pdf.worker.min.js (copied from
// node_modules/pdfjs-dist/build) so PDF viewing works offline/self-hosted.
// Keep the copy in sync with the pdfjs-dist version pinned in package.json.
const PDFJS_WORKER_URL = '/pdf.worker.min.js'

// New highlights default to the color used last (sticky highlighter pen).
const LAST_COLOR_KEY = 'pdf-highlight-color'
const readLastColor = (): string => {
  try {
    const stored = window.localStorage.getItem(LAST_COLOR_KEY)
    if (stored && HIGHLIGHT_PALETTE.some((c) => c.value === stored)) return stored
  } catch {
    // SSR or storage unavailable — fall through to the default.
  }
  return DEFAULT_HIGHLIGHT_COLOR
}

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
  /**
   * Batch variant: called with every quote carrying a given tag (plus the tag)
   * when the user clicks "Ask AI about <tag>" in the sidebar. Same wiring as
   * onChatAboutHighlight — omitted where no chat is wired, hiding the button.
   */
  onChatAboutHighlights?: (quotes: string[], tag: string) => void
}

// memo: the parent's tab-switch state changes must not re-render the viewer —
// each re-render creates a fresh defaultLayoutPlugin and re-runs pdf.js layout,
// which costs seconds on a large book. Props are a string, a number and a
// stable callback, so the shallow compare is exact.
export const PDFViewer = memo(function PDFViewer({
  sourceId,
  initialPage = 0,
  onChatAboutHighlight,
  onChatAboutHighlights,
}: PDFViewerProps) {
  const { t } = useTranslation()
  const layoutPlugin = defaultLayoutPlugin()

  const { data: annotations = [] } = useSourceAnnotations(sourceId)
  // Union of tags across the doc — feeds the popover's quick-add suggestions.
  const allTags = useMemo(
    () => [...new Set(annotations.flatMap((a) => a.tags ?? []))],
    [annotations]
  )
  const createAnnotation = useCreateAnnotation(sourceId)
  const updateAnnotation = useUpdateAnnotation(sourceId)
  const deleteAnnotation = useDeleteAnnotation(sourceId)

  // Which EXISTING highlight's popover is open (click position is where the
  // user clicked the overlay, so the popover appears right under the cursor).
  // noteMode: opened via the selection toolbar's "Note" action — the popover
  // starts with the note editor expanded and focused.
  const [activeAnnotation, setActiveAnnotation] = useState<{
    annotation: Annotation
    top: number
    left: number
    noteMode?: boolean
  } | null>(null)

  // Anchor awareness (pdf-block-ingestion D3): once the source is parsed, load
  // the active highlight's page overlay so clicking a highlight can select the
  // block it anchors to (for the popover's section breadcrumb). Overlay is
  // light (bbox only) and only fetched while a popover is open on a parsed page.
  const parseStatus = useParseStatus(sourceId)
  const isParsed = parseStatus.isSuccess
  const activePage = activeAnnotation?.annotation.page
  const { data: pageBlocks } = usePageBlocks(sourceId, activePage, {
    enabled: isParsed && activePage != null,
  })
  const activeBlockSeq = selectedBlockSeq(
    activeAnnotation?.annotation,
    pageBlocks?.blocks
  )

  // Sticky highlighter pen: new highlights use the color picked last.
  const [lastColor, setLastColor] = useState(readLastColor)
  const rememberColor = (color: string) => {
    setLastColor(color)
    try {
      window.localStorage.setItem(LAST_COLOR_KEY, color)
    } catch {
      // Non-persistent preference is still fine.
    }
  }

  // renderHighlightTarget/renderHighlights close over `annotations` and the
  // mutation functions below — recreated every render alongside layoutPlugin
  // (see comment above), so they never see stale data. `highlightPlugin`
  // itself is a plain factory (no internal React state keyed off identity),
  // matching how `defaultLayoutPlugin()` is already used unmemoized here.
  const renderHighlightTarget = (props: RenderHighlightTargetProps) => {
    const createHighlight = (color: string) =>
      createAnnotation.mutateAsync({
        page: props.selectionRegion.pageIndex + 1,
        rect: props.highlightAreas,
        color,
        quote: props.selectedText,
      })

    return (
      <div
        style={{
          position: 'absolute',
          left: `${props.selectionRegion.left}%`,
          top: `${props.selectionRegion.top + props.selectionRegion.height}%`,
          transform: 'translateY(4px)',
          zIndex: 50,
        }}
      >
        {/* Selection toolbar: pick a color to highlight, add a highlight with
            a note, or send the passage to the chat. */}
        <div
          role="toolbar"
          aria-label={t('sources.annotations.addHighlight')}
          className="flex items-center gap-2 rounded-lg border border-border bg-popover px-2.5 py-1.5 shadow-[var(--shadow)]"
        >
          <ColorDots
            size="sm"
            selected={lastColor}
            onPick={(color) => {
              rememberColor(color)
              createHighlight(color).catch(() => {
                // Failure already surfaced by the mutation's error toast.
              })
              props.cancel()
            }}
          />
          <span className="h-4 w-px bg-border" aria-hidden="true" />
          <button
            type="button"
            className="flex items-center gap-1 text-xs font-medium text-popover-foreground hover:text-primary"
            onClick={(e) => {
              const { clientX, clientY } = e
              createHighlight(lastColor)
                .then((created) =>
                  setActiveAnnotation({
                    annotation: created,
                    top: clientY,
                    left: clientX,
                    noteMode: true,
                  })
                )
                .catch(() => {
                  // Failure already surfaced by the mutation's error toast.
                })
              props.cancel()
            }}
          >
            <StickyNote className="h-3.5 w-3.5" aria-hidden="true" />
            {t('sources.annotations.addNote')}
          </button>
          {onChatAboutHighlight && (
            <button
              type="button"
              className="flex items-center gap-1 text-xs font-medium text-primary hover:opacity-80"
              onClick={() => {
                onChatAboutHighlight(props.selectedText)
                props.cancel()
              }}
            >
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
              {t('sources.annotations.askAi')}
            </button>
          )}
        </div>
      </div>
    )
  }

  const renderHighlights = (props: RenderHighlightsProps) => (
    <div>
      {annotations.map((annotation) =>
        annotation.rect
          .filter((area) => area.pageIndex === props.pageIndex)
          .map((area, idx) => (
            <div
              key={`${annotation.id}-${idx}`}
              data-highlight-id={annotation.id}
              onClick={(e) => {
                e.stopPropagation()
                setActiveAnnotation({ annotation, top: e.clientY, left: e.clientX })
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.opacity = '0.6'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.opacity = '0.4'
              }}
              style={{
                ...props.getCssProperties(area, props.rotation),
                background: annotation.color,
                opacity: 0.4,
                cursor: 'pointer',
                pointerEvents: 'auto',
                transition: 'opacity 0.15s',
                // pdf.js's (invisible) text layer sits at z-index 1 and would
                // otherwise swallow every click; the visible glyphs are on the
                // canvas below, so painting above the text layer changes
                // nothing visually but makes the highlight clickable.
                zIndex: 2,
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
        sourceId={sourceId}
        onJumpTo={(annotation) => {
          const area = annotation.rect[0]
          if (area) highlightPluginInstance.jumpToHighlightArea(area)
        }}
        onAskAiAboutTag={
          onChatAboutHighlights
            ? (tag) => {
                const quotes = annotations
                  .filter((a) => a.tags?.includes(tag))
                  .map((a) => a.quote)
                  .filter((q): q is string => !!q)
                onChatAboutHighlights(quotes, tag)
              }
            : undefined
        }
      />

      {activeAnnotation && (
        <AnnotationHighlightPopover
          annotation={activeAnnotation.annotation}
          top={activeAnnotation.top}
          left={activeAnnotation.left}
          sourceId={sourceId}
          blockSeq={activeBlockSeq}
          onClose={() => setActiveAnnotation(null)}
          startInNoteMode={activeAnnotation.noteMode}
          onSaveNote={(note) => {
            updateAnnotation.mutate({ id: activeAnnotation.annotation.id, data: { note } })
            setActiveAnnotation(null)
          }}
          onChangeColor={(color) => {
            rememberColor(color)
            updateAnnotation.mutate({ id: activeAnnotation.annotation.id, data: { color } })
            setActiveAnnotation((prev) =>
              prev ? { ...prev, annotation: { ...prev.annotation, color } } : prev
            )
          }}
          onSaveTags={(tags) => {
            updateAnnotation.mutate({ id: activeAnnotation.annotation.id, data: { tags } })
            // Optimistic local update so the popover reflects the change at once.
            setActiveAnnotation((prev) =>
              prev ? { ...prev, annotation: { ...prev.annotation, tags } } : prev
            )
          }}
          allTags={allTags}
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
