import type { AxiosResponse } from 'axios'

import apiClient, { get, post, put, patch, del } from './client'
import {
  SourceListResponse,
  SourceDetailResponse,
  SourceResponse,
  SourceSectionResponse,
  SourceStatusResponse,
  CreateSourceRequest,
  UpdateSourceRequest,
  Annotation,
  CreateAnnotationRequest,
  UpdateAnnotationRequest,
  Block,
  PageBlocksResponse,
  ParseStatusResponse
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

  // Document Foundation Track C (C2): chapter tree for chaptered sources.
  // `summary` is always inlined; `content` only when includeContent=true
  // (keeps the payload light — see coordinator Decision Q-section-content-payload).
  getSections: async (id: string, includeContent = false) => {
    return get<SourceSectionResponse>(
      `/sources/${id}/sections${includeContent ? '?include_content=true' : ''}`
    )
  },

  // Needs full AxiosResponse<Blob> for binary download — stays on raw apiClient
  downloadFile: async (id: string): Promise<AxiosResponse<Blob>> => {
    return apiClient.get(`/sources/${id}/download`, {
      responseType: 'blob',
    })
  },

  // pdf-block-ingestion Track C (C1): typed-block read endpoints. Every read
  // targets the source's CURRENT parse generation and 404s on an un-parsed
  // source (the frontend surfaces that as legacy/unparsed, not an error toast).

  // Parse status header for the current generation (poll target). 404 = never
  // parsed — the caller (useParseStatus) treats the error as "unparsed".
  getParseStatus: async (id: string) => {
    return get<ParseStatusResponse>(`/sources/${id}/parse`)
  },

  // One page's blocks in reading (seq) order. Overlay projection by default
  // (seq/type/page/bbox); `includeText` adds text/latex/section_path/table_data.
  getPageBlocks: async (id: string, page: number, includeText = false) => {
    return get<PageBlocksResponse>(`/sources/${id}/blocks`, {
      params: { page, include_text: includeText },
    })
  },

  // One full block (point-get) including text/latex/section_path/table_data.
  getBlock: async (id: string, seq: number) => {
    return get<Block>(`/sources/${id}/blocks/${seq}`)
  },

  // pdf-block-ingestion Track C2 (Decision #8): explicitly rebuild the block
  // substrate (build_blocks force=true), bypassing the content-hash gate — the
  // deliberate re-parse trigger behind the Re-process button. Returns the queued
  // command id + the generation the new parse will write. 409 while a parse is
  // already building for this source.
  reparse: async (id: string) => {
    return post<{ command_id: string; gen_expected: number }>(
      `/sources/${id}/reparse`
    )
  },
}

// Document Foundation Phase4: PDF highlight annotations. Note the last two
// (update/delete) are NOT nested under /sources/{id} — they address the
// annotation directly, mirroring the backend router's flat routes.
export const annotationsApi = {
  list: async (sourceId: string) => {
    return get<Annotation[]>(`/sources/${sourceId}/annotations`)
  },

  create: async (sourceId: string, data: CreateAnnotationRequest) => {
    return post<Annotation>(`/sources/${sourceId}/annotations`, data)
  },

  update: async (annotationId: string, data: UpdateAnnotationRequest) => {
    return patch<Annotation>(`/annotations/${annotationId}`, data)
  },

  delete: async (annotationId: string) => {
    await del(`/annotations/${annotationId}`)
  },
}
