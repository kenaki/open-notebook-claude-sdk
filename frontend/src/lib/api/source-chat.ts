import { get, post, put, del, streamFetch } from './client'
import {
  SourceChatSession,
  SourceChatSessionWithMessages,
  CreateSourceChatSessionRequest,
  UpdateSourceChatSessionRequest,
  SendMessageRequest
} from '@/lib/types/api'

export const sourceChatApi = {
  // Session management
  createSession: async (sourceId: string, data: Omit<CreateSourceChatSessionRequest, 'source_id'>) => {
    // Extract clean ID without "source:" prefix for the request body
    const cleanId = sourceId.startsWith('source:') ? sourceId.slice(7) : sourceId
    return post<SourceChatSession>(
      `/sources/${sourceId}/chat/sessions`,
      { ...data, source_id: cleanId }
    )
  },

  listSessions: async (sourceId: string) => {
    return get<SourceChatSession[]>(`/sources/${sourceId}/chat/sessions`)
  },

  getSession: async (sourceId: string, sessionId: string) => {
    return get<SourceChatSessionWithMessages>(`/sources/${sourceId}/chat/sessions/${sessionId}`)
  },

  updateSession: async (sourceId: string, sessionId: string, data: UpdateSourceChatSessionRequest) => {
    return put<SourceChatSession>(`/sources/${sourceId}/chat/sessions/${sessionId}`, data)
  },

  deleteSession: async (sourceId: string, sessionId: string) => {
    await del(`/sources/${sourceId}/chat/sessions/${sessionId}`)
  },

  sendMessage: (sourceId: string, sessionId: string, data: SendMessageRequest) =>
    streamFetch(`/api/sources/${sourceId}/chat/sessions/${sessionId}/messages`, data),
}
