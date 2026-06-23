import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { notebooksApi } from '@/lib/api/notebooks'
import { sourcesApi } from '@/lib/api/sources'
import { notesApi } from '@/lib/api/notes'
import { chatApi } from '@/lib/api/chat'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'
import { CreateNotebookRequest, UpdateNotebookRequest, NotebookResponse } from '@/lib/types/api'

// Mirror the page size used by useNotebookSources so the prefetched first page
// is an interchangeable cache entry for the workspace's infinite query.
const NOTEBOOK_SOURCES_PAGE_SIZE = 30

export function useNotebooks(archived?: boolean) {
  return useQuery({
    queryKey: [...QUERY_KEYS.notebooks, { archived }],
    queryFn: () => notebooksApi.list({ archived, order_by: 'updated desc' }),
  })
}

export function useNotebook(id: string) {
  return useQuery({
    queryKey: QUERY_KEYS.notebook(id),
    queryFn: () => notebooksApi.get(id),
    enabled: !!id,
  })
}

/**
 * Warm the cache for a notebook before it's opened (Track B1).
 *
 * - `prefetch(id)` — fired on hover/focus of a notebook card/row. Loads the same
 *   queries the workspace mounts (notebook meta, sources page 1, notes, chat
 *   sessions) using the SAME query fns/keys so the entries are interchangeable.
 *   `prefetchQuery`/`prefetchInfiniteQuery` are no-ops when the data is fresh.
 * - `seed(notebook)` — fired on click. Seeds the notebook metadata already present
 *   in the list item so the open gate is pre-satisfied and the title renders
 *   instantly. `old ?? notebook` never clobbers a fuller cached entry.
 */
export function useNotebookPrefetch() {
  const queryClient = useQueryClient()

  const prefetch = useCallback(
    (id: string) => {
      if (!id) return
      // Speculative hover/focus prefetches: opt out of the global query-error
      // toast (Track C1 convention) — a failed warm-up must stay silent.
      const silent = { meta: { silent: true } as const }
      queryClient.prefetchQuery({
        queryKey: QUERY_KEYS.notebook(id),
        queryFn: () => notebooksApi.get(id),
        ...silent,
      })
      // Sources: infinite query, page 1 only (matches useNotebookSources).
      queryClient.prefetchInfiniteQuery({
        queryKey: QUERY_KEYS.sourcesInfinite(id),
        queryFn: async ({ pageParam = 0 }) => {
          const data = await sourcesApi.list({
            notebook_id: id,
            limit: NOTEBOOK_SOURCES_PAGE_SIZE,
            offset: pageParam,
            sort_by: 'updated',
            sort_order: 'desc',
          })
          return {
            sources: data,
            nextOffset:
              data.length === NOTEBOOK_SOURCES_PAGE_SIZE ? pageParam + data.length : undefined,
          }
        },
        initialPageParam: 0,
        ...silent,
      })
      queryClient.prefetchQuery({
        queryKey: QUERY_KEYS.notes(id),
        queryFn: () => notesApi.list({ notebook_id: id }),
        ...silent,
      })
      queryClient.prefetchQuery({
        queryKey: QUERY_KEYS.notebookChatSessions(id),
        queryFn: () => chatApi.listSessions(id),
        ...silent,
      })
    },
    [queryClient]
  )

  const seed = useCallback(
    (notebook: NotebookResponse) => {
      queryClient.setQueryData<NotebookResponse>(
        QUERY_KEYS.notebook(notebook.id),
        (old) => old ?? notebook
      )
    },
    [queryClient]
  )

  return { prefetch, seed }
}

export function useCreateNotebook() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (data: CreateNotebookRequest) => notebooksApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
      toast({
        title: t('common.success'),
        description: t('notebooks.createSuccess'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}

export function useUpdateNotebook() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateNotebookRequest }) =>
      notebooksApi.update(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebook(id) })
      toast({
        title: t('common.success'),
        description: t('notebooks.updateSuccess'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}

export function useNotebookDeletePreview(id: string, enabled: boolean = false) {
  return useQuery({
    queryKey: [...QUERY_KEYS.notebook(id), 'delete-preview'],
    queryFn: () => notebooksApi.deletePreview(id),
    enabled: !!id && enabled,
  })
}

export function useDeleteNotebook() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({
      id,
      deleteExclusiveSources = false,
    }: {
      id: string
      deleteExclusiveSources?: boolean
    }) => notebooksApi.delete(id, deleteExclusiveSources),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
      // Also invalidate sources since some may have been deleted
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      toast({
        title: t('common.success'),
        description: t('notebooks.deleteSuccess'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}