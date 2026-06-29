import { get, post, put, del } from './client'
import {
  SourceChatSession,
  SourceChatSessionWithMessages,
  CreateSourceChatSessionRequest,
  UpdateSourceChatSessionRequest,
  SendMessageRequest
} from '@/lib/types/api'

// Background-jobs C3: the send endpoint now returns 202 + {job_id, session_id}.
export interface SendSourceChatJobResponse {
  job_id: string
  session_id: string
}

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

  // Background-jobs C3: POST → 202 {job_id, session_id}; the Track-B poller
  // delivers the answer by invalidating sourceChatSession on job completion.
  sendMessage: (sourceId: string, sessionId: string, data: SendMessageRequest) =>
    post<SendSourceChatJobResponse>(
      `/sources/${sourceId}/chat/sessions/${sessionId}/messages`,
      data
    ),
}
