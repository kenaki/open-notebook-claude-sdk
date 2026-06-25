import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notesApi } from '@/lib/api/notes'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useErrorToast } from '@/lib/hooks/use-error-toast'
import { CreateNoteRequest, UpdateNoteRequest } from '@/lib/types/api'

export function useNotes(notebookId?: string) {
  return useQuery({
    queryKey: QUERY_KEYS.notes(notebookId),
    queryFn: () => notesApi.list({ notebook_id: notebookId }),
    enabled: !!notebookId,
  })
}

export function useNote(id?: string, options?: { enabled?: boolean }) {
  const noteId = id ?? ''
  return useQuery({
    queryKey: QUERY_KEYS.note(noteId),
    queryFn: () => notesApi.get(noteId),
    enabled: !!noteId && (options?.enabled ?? true),
  })
}

export function useCreateNote() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()
  const errorToast = useErrorToast()

  return useMutation({
    mutationFn: (data: CreateNoteRequest) => notesApi.create(data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.notes(variables.notebook_id)
      })
      toast({
        title: t('common.success'),
        description: t('notebooks.noteCreatedSuccess'),
      })
    },
    onError: (error) => errorToast(error, 'notebooks.failedToCreateNote'),
  })
}

export function useUpdateNote() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()
  const errorToast = useErrorToast()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateNoteRequest }) =>
      notesApi.update(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notes() })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.note(id) })
      toast({
        title: t('common.success'),
        description: t('notebooks.noteUpdatedSuccess'),
      })
    },
    onError: (error) => errorToast(error, 'notebooks.failedToUpdateNote'),
  })
}

export function useDeleteNote() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()
  const errorToast = useErrorToast()

  return useMutation({
    mutationFn: (id: string) => notesApi.delete(id),
    onSuccess: () => {
      // Broad on purpose: the delete mutation carries only the note id (no notebook id),
      // so we can't scope to one notebook's list. Invalidate the whole `['notes']` tree.
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      toast({
        title: t('common.success'),
        description: t('notebooks.noteDeletedSuccess'),
      })
    },
    onError: (error) => errorToast(error, 'notebooks.failedToDeleteNote'),
  })
}
