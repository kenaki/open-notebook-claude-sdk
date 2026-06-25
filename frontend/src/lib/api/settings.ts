import { get, put } from './client'
import { SettingsResponse } from '@/lib/types/api'

export const settingsApi = {
  get: async () => {
    return get<SettingsResponse>('/settings')
  },

  update: async (data: Partial<SettingsResponse>) => {
    return put<SettingsResponse>('/settings', data)
  },
}
