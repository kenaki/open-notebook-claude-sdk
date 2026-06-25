import type { AxiosResponse } from 'axios'

import apiClient, { get, post, put, del } from './client'
import {
  SourceListResponse,
  SourceDetailResponse,
  SourceResponse,
  SourceStatusResponse,
  CreateSourceRequest,
  UpdateSourceRequest
} from '@/lib/types/api'

export const sourcesApi = {
  list: async (params?: {
    notebook_id?: string
    limit?: number
    offset?: number
    sort_by?: 'created' | 'updated'
    sort_order?: 'asc' | 'desc'
  }) => {
    return get<SourceListResponse[]>('/sources', { params })
  },

  get: async (id: string) => {
    return get<SourceDetailResponse>(`/sources/${id}`)
  },

  create: async (data: CreateSourceRequest & { file?: File }) => {
    // Always use FormData to match backend expectations
    const formData = new FormData()

    // Add basic fields
    formData.append('type', data.type)

    if (data.notebooks !== undefined) {
      formData.append('notebooks', JSON.stringify(data.notebooks))
    }
    if (data.notebook_id) {
      formData.append('notebook_id', data.notebook_id)
    }
    if (data.title) {
      formData.append('title', data.title)
    }
    if (data.url) {
      formData.append('url', data.url)
    }
    if (data.content) {
      formData.append('content', data.content)
    }
    if (data.transformations !== undefined) {
      formData.append('transformations', JSON.stringify(data.transformations))
    }

    const dataWithFile = data as CreateSourceRequest & { file?: File }
    if (dataWithFile.file instanceof File) {
      formData.append('file', dataWithFile.file)
    }

    formData.append('embed', String(data.embed ?? false))
    formData.append('delete_source', String(data.delete_source ?? false))
    formData.append('async_processing', String(data.async_processing ?? false))

    return post<SourceResponse>('/sources', formData)
  },

  update: async (id: string, data: UpdateSourceRequest) => {
    return put<SourceListResponse>(`/sources/${id}`, data)
  },

  delete: async (id: string) => {
    await del(`/sources/${id}`)
  },

  status: async (id: string) => {
    return get<SourceStatusResponse>(`/sources/${id}/status`)
  },

  upload: async (file: File, notebook_id: string) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('notebook_id', notebook_id)
    formData.append('type', 'upload')
    formData.append('async_processing', 'true')

    return post<SourceResponse>('/sources', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },

  retry: async (id: string) => {
    return post<SourceResponse>(`/sources/${id}/retry`)
  },

  // Needs full AxiosResponse<Blob> for binary download — stays on raw apiClient
  downloadFile: async (id: string): Promise<AxiosResponse<Blob>> => {
    return apiClient.get(`/sources/${id}/download`, {
      responseType: 'blob',
    })
  },
}
