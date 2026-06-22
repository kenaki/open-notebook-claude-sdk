'use client'

import { useEffect, useState } from 'react'
import { Play } from 'lucide-react'
import { getApiUrl } from '@/lib/config'
import type { MediaItem } from '@/lib/types/api'

// Resolve a fetchable src for a backend media url. The backend returns a path
// like "/api/chat/media/<file>"; prefix it with the resolved API base (which is
// "" when the frontend proxies through Next.js rewrites, or an absolute host
// otherwise). getApiUrl() caches after the first call.
function useResolvedSrc(url: string): string {
  const [base, setBase] = useState('')
  useEffect(() => {
    let active = true
    getApiUrl()
      .then((u) => {
        if (active) setBase(u)
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [])
  return `${base}${url}`
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

// A single 150×104 media tile (handoff §"Media attachments"). Image → cover
// thumbnail; video → first-frame poster + centered 40px play button + a duration
// pill (derived client-side from the loaded metadata when the backend has none).
// Filename sits bottom-left over a dark gradient in monospace.
function MediaTile({ item }: { item: MediaItem }) {
  const src = useResolvedSrc(item.url)
  const [duration, setDuration] = useState<string | null>(item.duration ?? null)

  return (
    <a
      href={src}
      target="_blank"
      rel="noopener noreferrer"
      className="relative block w-[150px] h-[104px] rounded-[10px] overflow-hidden border border-border bg-panel-2"
    >
      {item.type === 'image' ? (
        // eslint-disable-next-line @next/next/no-img-element -- src is a runtime-resolved API host (next/image needs a static domain allowlist)
        <img src={src} alt={item.label} className="w-full h-full object-cover" />
      ) : (
        <>
          <video
            src={src}
            preload="metadata"
            muted
            playsInline
            className="w-full h-full object-cover"
            onLoadedMetadata={(e) => {
              if (!item.duration && isFinite(e.currentTarget.duration)) {
                setDuration(formatDuration(e.currentTarget.duration))
              }
            }}
          />
          <span className="absolute inset-0 flex items-center justify-center">
            <span className="h-10 w-10 rounded-full bg-primary flex items-center justify-center shadow-[var(--shadow)]">
              <Play className="h-4 w-4 text-primary-foreground" fill="currentColor" />
            </span>
          </span>
          {duration && (
            <span className="absolute top-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-white">
              {duration}
            </span>
          )}
        </>
      )}
      <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-2 py-1">
        <span className="block truncate font-mono text-[10px] text-white">{item.label}</span>
      </span>
    </a>
  )
}

// Media attachments on a message, rendered as wrapping tiles (Plan D / Chunk 12).
export function MessageMedia({
  media,
  className,
}: {
  media: MediaItem[]
  className?: string
}) {
  if (!media || media.length === 0) return null
  return (
    <div className={`flex flex-wrap gap-2 ${className ?? ''}`}>
      {media.map((item, i) => (
        <MediaTile key={`${item.url}-${i}`} item={item} />
      ))}
    </div>
  )
}
