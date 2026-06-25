import { get, post, put, del } from './client'
import { NoteResponse, CreateNoteRequest, UpdateNoteRequest } from '@/lib/types/api'

export const notesApi = {
  list: async (params?: { notebook_id?: string }) => {
    return get<NoteResponse[]>('/notes', { params })
  },

  get: async (id: string) => {
    return get<NoteResponse>(`/notes/${id}`)
  },

  create: async (data: CreateNoteRequest) => {
    return post<NoteResponse>('/notes', data)
  },

  update: async (id: string, data: UpdateNoteRequest) => {
    return put<NoteResponse>(`/notes/${id}`, data)
  },

  delete: async (id: string) => {
    await del(`/notes/${id}`)
  },
}
