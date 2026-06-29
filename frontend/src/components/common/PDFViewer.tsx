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
import { useEffect, useState } from 'react'
import { useTranslation } from '@/lib/hooks/use-translation'

// Worker is served from the CDN to avoid Next.js webpack public/ copy complexity.
// Version must match the pdfjs-dist version pinned in package.json (^3.11.174).
const PDFJS_WORKER_URL =
  'https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.worker.min.js'

interface PDFViewerProps {
  sourceId: string
  /**
   * 0-based page index to open initially.
   * Phase3 will pass the citation page number here — prop is pre-wired
   * so Phase3 needs no PDFViewer changes.
   */
  initialPage?: number
}

export function PDFViewer({ sourceId, initialPage = 0 }: PDFViewerProps) {
  const { t } = useTranslation()
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const layoutPlugin = defaultLayoutPlugin()

  useEffect(() => {
    let objectUrl: string | null = null

    sourcesApi
      .downloadFile(sourceId)
      .then((response) => {
        objectUrl = URL.createObjectURL(response.data)
        setPdfUrl(objectUrl)
      })
      .catch((err) => {
        console.error('PDFViewer: failed to fetch PDF', err)
        setError(String(err?.message ?? err))
      })

    return () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceId])

  if (error) {
    return (
      <div className="flex items-center justify-center p-8 text-destructive">
        {error}
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
      <div style={{ height: '80vh' }}>
        <Viewer
          fileUrl={pdfUrl}
          plugins={[layoutPlugin]}
          initialPage={initialPage}
        />
      </div>
    </Worker>
  )
}
