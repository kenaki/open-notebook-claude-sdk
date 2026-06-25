'use client'

import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Link as LinkIcon, ExternalLink, Youtube } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { SourceDetailResponse } from '@/lib/types/api'

function getYouTubeVideoId(url: string): string | null {
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)/,
    /youtube\.com\/watch\?.*v=([^&\n?#]+)/
  ]

  for (const pattern of patterns) {
    const match = url.match(pattern)
    if (match) return match[1]
  }
  return null
}

interface SourceContentTabProps {
  source: SourceDetailResponse
}

export function SourceContentTab({ source }: SourceContentTabProps) {
  const { t } = useTranslation()

  const youTubeVideoId = useMemo(() => {
    if (!source.asset?.url) return null
    return getYouTubeVideoId(source.asset.url)
  }, [source.asset?.url])

  const isYouTubeUrl = Boolean(youTubeVideoId)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isYouTubeUrl && <Youtube className="h-5 w-5" />}
          {t('sources.content')}
        </CardTitle>
        {source.asset?.url && !isYouTubeUrl && (
          <CardDescription className="flex items-center gap-2">
            <LinkIcon className="h-4 w-4" />
            <a
              href={source.asset.url}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline text-blue-600"
            >
              {source.asset.url}
            </a>
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {isYouTubeUrl && youTubeVideoId && (
          <div className="mb-6">
            <div className="aspect-video rounded-lg overflow-hidden bg-black">
              <iframe
                src={`https://www.youtube.com/embed/${youTubeVideoId}`}
                title={t('common.accessibility.ytVideo')}
                className="w-full h-full"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
              />
            </div>
            {source.asset?.url && (
              <div className="mt-2">
                <a
                  href={source.asset.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-muted-foreground hover:underline inline-flex items-center gap-1"
                >
                  <ExternalLink className="h-3 w-3" />
                  {t('sources.openOnYoutube')}
                </a>
              </div>
            )}
          </div>
        )}
        <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none prose-headings:font-semibold prose-a:text-blue-600 prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-p:mb-4 prose-p:leading-7 prose-li:mb-2">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p className="mb-4">{children}</p>,
              h1: ({ children }) => <h1 className="text-2xl font-bold mt-6 mb-4">{children}</h1>,
              h2: ({ children }) => <h2 className="text-xl font-bold mt-5 mb-3">{children}</h2>,
              h3: ({ children }) => <h3 className="text-lg font-semibold mt-4 mb-2">{children}</h3>,
              ul: ({ children }) => <ul className="mb-4 list-disc pl-6">{children}</ul>,
              ol: ({ children }) => <ol className="mb-4 list-decimal pl-6">{children}</ol>,
              li: ({ children }) => <li className="mb-1">{children}</li>,
              table: ({ children }) => (
                <div className="my-4 overflow-x-auto">
                  <table className="min-w-full border-collapse border border-border">{children}</table>
                </div>
              ),
              thead: ({ children }) => <thead className="bg-muted">{children}</thead>,
              tbody: ({ children }) => <tbody>{children}</tbody>,
              tr: ({ children }) => <tr className="border-b border-border">{children}</tr>,
              th: ({ children }) => <th className="border border-border px-3 py-2 text-left font-semibold">{children}</th>,
              td: ({ children }) => <td className="border border-border px-3 py-2">{children}</td>,
            }}
          >
            {source.full_text || t('sources.noContent')}
          </ReactMarkdown>
        </div>
      </CardContent>
    </Card>
  )
}
