import { get, post, put, del } from './client'
import {
  NotebookResponse,
  CreateNotebookRequest,
  UpdateNotebookRequest,
  NotebookDeletePreview,
  NotebookDeleteResponse,
} from '@/lib/types/api'

export const notebooksApi = {
  list: async (params?: { archived?: boolean; order_by?: string }) => {
    return get<NotebookResponse[]>('/notebooks', { params })
  },

  get: async (id: string) => {
    return get<NotebookResponse>(`/notebooks/${id}`)
  },

  create: async (data: CreateNotebookRequest) => {
    return post<NotebookResponse>('/notebooks', data)
  },

  update: async (id: string, data: UpdateNotebookRequest) => {
    return put<NotebookResponse>(`/notebooks/${id}`, data)
  },

  deletePreview: async (id: string) => {
    return get<NotebookDeletePreview>(`/notebooks/${id}/delete-preview`)
  },

  delete: async (id: string, deleteExclusiveSources: boolean = false) => {
    return del<NotebookDeleteResponse>(`/notebooks/${id}`, {
      params: { delete_exclusive_sources: deleteExclusiveSources },
    })
  },

  addSource: async (notebookId: string, sourceId: string) => {
    return post(`/notebooks/${notebookId}/sources/${sourceId}`)
  },

  removeSource: async (notebookId: string, sourceId: string) => {
    return del(`/notebooks/${notebookId}/sources/${sourceId}`)
  },
}
