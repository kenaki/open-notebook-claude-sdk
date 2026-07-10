'use client'

import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Link as LinkIcon, ExternalLink, Youtube } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { sourcesApi } from '@/lib/api/sources'
import { SourceDetailResponse, SourceSectionNode } from '@/lib/types/api'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { SourceTOC, getSectionPageRangeLabel, type SectionActionKind } from './SourceTOC'
import { useSourceChat } from '@/lib/hooks/useSourceChat'
import { getApiUrl } from '@/lib/config'
import { cn } from '@/lib/utils'

const BLOCK_URL_PREFIX = 'block://'

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

/** DFS-flattens a section tree into document order (root before children). */
function flattenSections(nodes: SourceSectionNode[]): SourceSectionNode[] {
  const result: SourceSectionNode[] = []
  const walk = (list: SourceSectionNode[]) => {
    for (const node of list) {
      result.push(node)
      if (node.children?.length) walk(node.children)
    }
  }
  walk(nodes)
  return result
}

function findSectionById(nodes: SourceSectionNode[], id: string): SourceSectionNode | undefined {
  for (const node of nodes) {
    if (node.id === id) return node
    if (node.children?.length) {
      const found = findSectionById(node.children, id)
      if (found) return found
    }
  }
  return undefined
}

interface SourceContentTabProps {
  source: SourceDetailResponse
  /**
   * Card heading. Defaults to "Content". The Reader tab renders this component
   * for sources with no block substrate (URLs, transcripts, unparsed PDFs), and
   * passes its own label so the card doesn't contradict the tab.
   */
  title?: string
}

// memo: with keep-alive tabs this stays mounted while the user switches tabs;
// without it every tab switch re-renders (and ReactMarkdown re-parses) the whole
// active chapter. `source` is a stable state object from useSourceDetail.
export const SourceContentTab = memo(function SourceContentTab({
  source,
  title,
}: SourceContentTabProps) {
  const { t } = useTranslation()
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null)

  // C4: per-chapter AI actions dispatch to this source's chat. We tap the same
  // `useSourceChat` hook the source-detail page's ChatPanel uses; both instances
  // share the TanStack cache (keyed by source + session), so a "Summarize
  // section" message surfaces in the visible chat panel and auto-creates a
  // session when none exists. (Q-c4-chat-scope resolution.)
  const sourceChat = useSourceChat(source.id)
  const handleSectionAction = useCallback(
    (kind: SectionActionKind, section: SourceSectionNode) => {
      const title = section.title?.trim() || t('sources.untitledSection')
      // Include the section id so the chat model can call get_section(section_id)
      // to pull the actual chapter text, instead of guessing from the title and
      // parroting back the outline metadata (title / page / summary: null).
      const ref = `"${title}" (section_id: ${section.id})`
      const prompt =
        kind === 'summarize'
          ? `Summarize section ${ref}`
          : `Quiz me on section ${ref}`
      void sourceChat.sendMessage(prompt)
    },
    [sourceChat, t]
  )

  const youTubeVideoId = useMemo(() => {
    if (!source.asset?.url) return null
    return getYouTubeVideoId(source.asset.url)
  }, [source.asset?.url])

  const isYouTubeUrl = Boolean(youTubeVideoId)

  // Document Foundation Track C (C3): chapter tree for chaptered sources (PDFs /
  // long documents — Decision #12). Outline-only fetch first (summary inline,
  // no content) — lightweight, drives the TOC and the has_sections gate.
  const { data: sectionsData, isFetched: sectionsFetched } = useQuery({
    queryKey: ['sections', source.id],
    queryFn: () => sourcesApi.getSections(source.id),
    enabled: Boolean(source.id),
  })

  const hasSections = Boolean(sectionsData?.has_sections)
  const outlineSections = useMemo(() => sectionsData?.sections ?? [], [sectionsData])

  // E3: full_text is no longer on the source payload. For non-chaptered sources
  // the content tab lazy-loads the regenerated markdown from the dedicated
  // endpoint — only once we know there are no sections (avoids fetching a
  // whole book for chaptered PDFs that render via the section tree instead).
  const { data: fullTextData, isLoading: fullTextLoading } = useQuery({
    queryKey: ['sources', source.id, 'full-text'],
    queryFn: () => sourcesApi.getFullText(source.id),
    enabled: Boolean(source.id) && sectionsFetched && !hasSections,
  })

  // Resolved API base for rewriting block:// figure refs to their crop URL.
  const [apiBase, setApiBase] = useState('')
  useEffect(() => {
    let active = true
    getApiUrl()
      .then((u) => active && setApiBase(u))
      .catch(() => {})
    return () => {
      active = false
    }
  }, [])

  // Full (cleaned) content is fetched only once we know sections exist
  // (Q-section-content-payload default: summary inline, content on demand) —
  // one extra round trip per chaptered source, not one per chapter click.
  const { data: contentData, isLoading: contentLoading } = useQuery({
    queryKey: ['sections', source.id, 'content'],
    queryFn: () => sourcesApi.getSections(source.id, true),
    enabled: hasSections,
  })

  const contentSections = contentData?.sections ?? outlineSections

  // Default to the first section (document order) once the outline loads.
  useEffect(() => {
    if (!hasSections || activeSectionId) return
    const first = flattenSections(outlineSections)[0]
    if (first) setActiveSectionId(first.id)
  }, [hasSections, outlineSections, activeSectionId])

  const activeSection = activeSectionId ? findSectionById(contentSections, activeSectionId) : undefined
  const activeSectionRange = activeSection ? getSectionPageRangeLabel(activeSection) : null
  const isLoadingActiveContent = hasSections
    ? contentLoading && !activeSection?.content
    : fullTextLoading

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isYouTubeUrl && <Youtube className="h-5 w-5" />}
          {title ?? t('sources.content')}
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
        <div className={cn(hasSections && 'flex flex-col gap-6 lg:flex-row')}>
          {hasSections && (
            <SourceTOC
              sections={outlineSections}
              activeSectionId={activeSectionId}
              onSectionClick={setActiveSectionId}
              onSectionAction={handleSectionAction}
            />
          )}
          <div className={cn(hasSections && 'min-w-0 flex-1')}>
            {hasSections && (
              <div data-section-id={activeSection?.id} className="mb-4">
                <h2 className="text-xl font-bold">
                  {activeSection?.title?.trim() || t('sources.untitledSection')}
                </h2>
                {activeSectionRange && (
                  <p className="mt-1 text-sm text-muted-foreground">{activeSectionRange}</p>
                )}
                {activeSection?.summary?.trim() && (
                  <div className="mt-3 rounded-lg border border-border bg-muted/50 px-3 py-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {t('sources.sectionSummary')}
                    </p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">
                      {activeSection.summary}
                    </p>
                  </div>
                )}
              </div>
            )}
            {isLoadingActiveContent ? (
              <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
                <LoadingSpinner size="sm" />
                {t('sources.loadingChapters')}
              </div>
            ) : (
              <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none prose-headings:font-semibold prose-a:text-blue-600 prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-p:mb-4 prose-p:leading-7 prose-li:mb-2">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={{
                    // block://<seq> figure refs resolve to the crop endpoint
                    // (same base convention as chat/reader). Plain http(s) image
                    // URLs pass through unchanged.
                    img: ({ src, alt }) => {
                      const resolved =
                        typeof src === 'string' && src.startsWith(BLOCK_URL_PREFIX)
                          ? `${apiBase}/api/sources/${source.id}/blocks/${src.slice(BLOCK_URL_PREFIX.length)}/image`
                          : src
                      return (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={resolved}
                          alt={alt ?? ''}
                          className="my-4 h-auto max-w-full rounded border border-border"
                        />
                      )
                    },
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
                  {(hasSections ? activeSection?.content : fullTextData?.full_text) || t('sources.noContent')}
                </ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
})
