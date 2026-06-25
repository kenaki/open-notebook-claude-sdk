import { get, post, put, del } from './client'
import {
  Transformation,
  CreateTransformationRequest,
  UpdateTransformationRequest,
  ExecuteTransformationRequest,
  ExecuteTransformationResponse,
  DefaultPrompt
} from '@/lib/types/transformations'

export const transformationsApi = {
  list: async () => {
    return get<Transformation[]>('/transformations')
  },

  get: async (id: string) => {
    return get<Transformation>(`/transformations/${id}`)
  },

  create: async (data: CreateTransformationRequest) => {
    return post<Transformation>('/transformations', data)
  },

  update: async (id: string, data: UpdateTransformationRequest) => {
    return put<Transformation>(`/transformations/${id}`, data)
  },

  delete: async (id: string) => {
    await del(`/transformations/${id}`)
  },

  execute: async (data: ExecuteTransformationRequest) => {
    return post<ExecuteTransformationResponse>('/transformations/execute', data)
  },

  getDefaultPrompt: async () => {
    return get<DefaultPrompt>('/transformations/default-prompt')
  },

  updateDefaultPrompt: async (prompt: { transformation_instructions: string }) => {
    return put<DefaultPrompt>('/transformations/default-prompt', prompt)
  },
}
