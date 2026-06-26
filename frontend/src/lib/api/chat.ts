import { get, post, put, del } from './client'
import {
  NotebookChatSession,
  NotebookChatSessionWithMessages,
  CreateNotebookChatSessionRequest,
  UpdateNotebookChatSessionRequest,
  SendNotebookChatMessageRequest,
  BuildContextRequest,
  BuildContextResponse,
  ExecuteChatJobResponse,
  MediaItem,
} from '@/lib/types/api'

export const chatApi = {
  // Session management
  listSessions: async (notebookId: string) => {
    return get<NotebookChatSession[]>(`/chat/sessions`, { params: { notebook_id: notebookId } })
  },

  createSession: async (data: CreateNotebookChatSessionRequest) => {
    return post<NotebookChatSession>(`/chat/sessions`, data)
  },

  getSession: async (sessionId: string) => {
    return get<NotebookChatSessionWithMessages>(`/chat/sessions/${sessionId}`)
  },

  updateSession: async (sessionId: string, data: UpdateNotebookChatSessionRequest) => {
    return put<NotebookChatSession>(`/chat/sessions/${sessionId}`, data)
  },

  deleteSession: async (sessionId: string) => {
    await del(`/chat/sessions/${sessionId}`)
  },

  // Messaging — submits to background worker, returns {job_id, session_id}
  sendMessage: async (data: SendNotebookChatMessageRequest) => {
    return post<ExecuteChatJobResponse>(`/chat/execute`, data)
  },

  buildContext: async (data: BuildContextRequest) => {
    return post<BuildContextResponse>(`/chat/context`, data)
  },

  // Upload an image/video to attach to a chat message (Plan D / Chunk 12).
  // The client.ts interceptor strips Content-Type so the browser sets the
  // multipart boundary. Returns the MediaItem the composer stages in `pending[]`.
  uploadMedia: async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return post<MediaItem>(`/chat/media`, formData)
  },
}

export default chatApi
