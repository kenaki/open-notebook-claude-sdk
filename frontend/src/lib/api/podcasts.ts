import { getApiUrl } from '@/lib/config'
import { get, post, put, del } from './client'
import {
  PodcastEpisode,
  EpisodeProfile,
  SpeakerProfile,
  Language,
  PodcastGenerationRequest,
  PodcastGenerationResponse,
} from '@/lib/types/podcasts'

export type EpisodeProfileInput = Omit<EpisodeProfile, 'id'>
export type SpeakerProfileInput = Omit<SpeakerProfile, 'id'>

export async function resolvePodcastAssetUrl(path?: string | null): Promise<string | undefined> {
  if (!path) {
    return undefined
  }

  if (/^https?:\/\//i.test(path)) {
    return path
  }

  const base = await getApiUrl()

  if (path.startsWith('/')) {
    return `${base}${path}`
  }

  return `${base}/${path}`
}

export const podcastsApi = {
  listEpisodes: async () => {
    return get<PodcastEpisode[]>('/podcasts/episodes')
  },

  deleteEpisode: async (episodeId: string) => {
    await del(`/podcasts/episodes/${episodeId}`)
  },

  retryEpisode: async (episodeId: string) => {
    return post<{ job_id: string; message: string }>(`/podcasts/episodes/${episodeId}/retry`)
  },

  listEpisodeProfiles: async () => {
    return get<EpisodeProfile[]>('/episode-profiles')
  },

  createEpisodeProfile: async (payload: EpisodeProfileInput) => {
    return post<EpisodeProfile>('/episode-profiles', payload)
  },

  updateEpisodeProfile: async (profileId: string, payload: EpisodeProfileInput) => {
    return put<EpisodeProfile>(`/episode-profiles/${profileId}`, payload)
  },

  deleteEpisodeProfile: async (profileId: string) => {
    await del(`/episode-profiles/${profileId}`)
  },

  duplicateEpisodeProfile: async (profileId: string) => {
    return post<EpisodeProfile>(`/episode-profiles/${profileId}/duplicate`)
  },

  listSpeakerProfiles: async () => {
    return get<SpeakerProfile[]>('/speaker-profiles')
  },

  createSpeakerProfile: async (payload: SpeakerProfileInput) => {
    return post<SpeakerProfile>('/speaker-profiles', payload)
  },

  updateSpeakerProfile: async (profileId: string, payload: SpeakerProfileInput) => {
    return put<SpeakerProfile>(`/speaker-profiles/${profileId}`, payload)
  },

  deleteSpeakerProfile: async (profileId: string) => {
    await del(`/speaker-profiles/${profileId}`)
  },

  duplicateSpeakerProfile: async (profileId: string) => {
    return post<SpeakerProfile>(`/speaker-profiles/${profileId}/duplicate`)
  },

  generatePodcast: async (payload: PodcastGenerationRequest) => {
    return post<PodcastGenerationResponse>('/podcasts/generate', payload)
  },

  listLanguages: async () => {
    return get<Language[]>('/languages')
  },
}
