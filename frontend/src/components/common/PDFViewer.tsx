'use client'

// NOTE: @react-pdf-viewer/core requires pdfjs-dist ^3.x and has a peer-dep
// of react >=16.8.0 <19.0.0. This project uses React 19 — install with
// --legacy-peer-deps at integration. If runtime breakage occurs, fall back
// to `react-pdf` + a custom page-navigation layer (see coordinator Decision #13).
import { Worker, Viewer } from '@react-pdf-viewer/core'
import { defaultLayoutPlugin } from '@react-pdf-viewer/default-layout'
import '@react-pdf-viewer/core/lib/styles/index.css'
import '@react-pdf-viewer/default-layout/lib/styles/index.css'
import { sourcesApi } from '@/lib/api/sources'
import { memo, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from '@/lib/hooks/use-translation'

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
}

// memo: the parent's tab-switch state changes must not re-render the viewer —
// each re-render creates a fresh defaultLayoutPlugin and re-runs pdf.js layout,
// which costs seconds on a large book. Props are a string and a number, so the
// shallow compare is exact.
export const PDFViewer = memo(function PDFViewer({
  sourceId,
  initialPage = 0,
}: PDFViewerProps) {
  const { t } = useTranslation()
  const layoutPlugin = defaultLayoutPlugin()

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
    <Worker workerUrl={PDFJS_WORKER_URL}>
      <div className="min-h-0 flex-1">
        <Viewer
          fileUrl={pdfUrl}
          plugins={[layoutPlugin]}
          initialPage={initialPage}
        />
      </div>
    </Worker>
  )
})
