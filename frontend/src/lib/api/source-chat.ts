import { get, post, put, del } from './client'
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

  // Messaging with streaming — hand-rolled fetch kept intact for B9
  sendMessage: (sourceId: string, sessionId: string, data: SendMessageRequest) => {
    let token = null
    if (typeof window !== 'undefined') {
      const authStorage = localStorage.getItem('auth-storage')
      if (authStorage) {
        try {
          const { state } = JSON.parse(authStorage)
          if (state?.token) {
            token = state.token
          }
        } catch (error) {
          console.error('Error parsing auth storage:', error)
        }
      }
    }

    const url = `/api/sources/${sourceId}/chat/sessions/${sessionId}/messages`

    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token && { 'Authorization': `Bearer ${token}` })
      },
      body: JSON.stringify(data)
    }).then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      return response.body
    })
  },
}
