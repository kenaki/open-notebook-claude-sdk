import { post, streamFetch } from './client'
import { SearchRequest, SearchResponse, AskRequest } from '@/lib/types/search'

export const searchApi = {
  // Standard search (non-streaming)
  search: async (params: SearchRequest) => {
    return post<SearchResponse>('/search', params)
  },

  askKnowledgeBase: (params: AskRequest) => streamFetch('/api/search/ask', params),
}
