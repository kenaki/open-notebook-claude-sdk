import { get } from './client'
import { CitingSession, CitingCountsResponse } from '@/lib/types/api'

/**
 * Reverse "linked chats" lookups (cross-interface-study Track B4). These read
 * the `cites_annotation` edge the opposite direction from the write path: given
 * an annotation, which chat sessions cite it; and, in bulk, how many sessions
 * cite each annotation of a source (for the sidebar badges).
 *
 * NOTE: a separate `annotationsApi` (CRUD) lives in `./sources`; this module is
 * import-scoped, so the same name in the two files never collides.
 */
export const annotationsApi = {
  getCitingSessions: (annotationId: string) =>
    get<CitingSession[]>(`/annotations/${annotationId}/citing-sessions`),

  getCitingCounts: (sourceId: string) =>
    get<CitingCountsResponse>(`/sources/${sourceId}/annotations/citing-counts`),
}
