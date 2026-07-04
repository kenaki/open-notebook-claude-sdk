import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { annotationsApi } from '@/lib/api/sources'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useErrorToast } from '@/lib/hooks/use-error-toast'
import { CreateAnnotationRequest, UpdateAnnotationRequest } from '@/lib/types/api'

/**
 * Document Foundation Phase4: PDF highlight annotations for a source.
 * List query is scoped per-source; mutations invalidate that same key so a
 * created/updated/deleted highlight reflects immediately in both the
 * PDFViewer overlay and the annotations sidebar.
 */
export function useSourceAnnotations(sourceId?: string) {
  return useQuery({
    queryKey: QUERY_KEYS.sourceAnnotations(sourceId ?? ''),
    queryFn: () => annotationsApi.list(sourceId as string),
    enabled: !!sourceId,
  })
}

export function useCreateAnnotation(sourceId: string) {
  const queryClient = useQueryClient()
  const errorToast = useErrorToast()

  return useMutation({
    mutationFn: (data: CreateAnnotationRequest) => annotationsApi.create(sourceId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sourceAnnotations(sourceId) })
    },
    onError: (error) => errorToast(error, 'sources.annotations.createFailed'),
  })
}

export function useUpdateAnnotation(sourceId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()
  const errorToast = useErrorToast()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateAnnotationRequest }) =>
      annotationsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sourceAnnotations(sourceId) })
      toast({
        title: t('common.success'),
        description: t('sources.annotations.updateSuccess'),
      })
    },
    onError: (error) => errorToast(error, 'sources.annotations.updateFailed'),
  })
}

export function useDeleteAnnotation(sourceId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()
  const errorToast = useErrorToast()

  return useMutation({
    mutationFn: (id: string) => annotationsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sourceAnnotations(sourceId) })
      toast({
        title: t('common.success'),
        description: t('sources.annotations.deleteSuccess'),
      })
    },
    onError: (error) => errorToast(error, 'sources.annotations.deleteFailed'),
  })
}
