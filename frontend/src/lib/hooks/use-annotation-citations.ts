import { useQuery } from '@tanstack/react-query'
import { annotationsApi } from '@/lib/api/annotations'

/**
 * Chat sessions that cite a given annotation, for the highlight popover's
 * "linked chats" section (cross-interface-study Track B4). Fetched lazily —
 * `enabled` is driven by the popover being open — so we don't hit the reverse
 * lookup for every rendered highlight overlay.
 *
 * INLINE query key (Track C owns `query-client.ts`'s QUERY_KEYS; this key stays
 * out of it deliberately).
 */
export function useAnnotationCitations(
  annotationId: string,
  { enabled }: { enabled: boolean }
) {
  return useQuery({
    queryKey: ['annotations', annotationId, 'citing-sessions'],
    queryFn: () => annotationsApi.getCitingSessions(annotationId),
    enabled: enabled && !!annotationId,
  })
}

/**
 * Bulk per-annotation citing counts for a source, powering the sidebar row
 * badges (cross-interface-study Track B4). One request per source; short
 * `staleTime` so a freshly-linked chat surfaces without hammering the endpoint.
 */
export function useAnnotationCitingCounts(sourceId?: string) {
  return useQuery({
    queryKey: ['annotations', 'citing-counts', sourceId],
    queryFn: () => annotationsApi.getCitingCounts(sourceId as string),
    enabled: !!sourceId,
    staleTime: 30_000,
  })
}
