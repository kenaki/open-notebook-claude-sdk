import { get, post, put, del } from './client'
import {
  Model,
  CreateModelRequest,
  ModelDefaults,
  ProviderAvailability,
  DiscoveredModel,
  ProviderSyncResult,
  AllProvidersSyncResult,
  ProviderModelCount,
  AutoAssignResult,
  ModelTestResult,
  ClaudeAgentModelConfig,
  UpdateClaudeAgentModelRequest,
} from '@/lib/types/models'

export const modelsApi = {
  list: async () => {
    return get<Model[]>('/models')
  },

  get: async (id: string) => {
    return get<Model>(`/models/${id}`)
  },

  create: async (data: CreateModelRequest) => {
    return post<Model>('/models', data)
  },

  delete: async (id: string) => {
    await del(`/models/${id}`)
  },

  getDefaults: async () => {
    return get<ModelDefaults>('/models/defaults')
  },

  updateDefaults: async (data: Partial<ModelDefaults>) => {
    return put<ModelDefaults>('/models/defaults', data)
  },

  /**
   * Get the Claude Agent (subscription chat) model configuration and options
   */
  getClaudeAgentModel: async () => {
    return get<ClaudeAgentModelConfig>('/models/claude-agent')
  },

  /**
   * Set which Claude model the Claude Agent uses (empty = follow CC default)
   */
  updateClaudeAgentModel: async (data: UpdateClaudeAgentModelRequest) => {
    return put<ClaudeAgentModelConfig>('/models/claude-agent', data)
  },

  getProviders: async () => {
    return get<ProviderAvailability>('/models/providers')
  },

  // Model Discovery API
  /**
   * Discover available models from a provider without registering them
   */
  discoverModels: async (provider: string) => {
    return get<DiscoveredModel[]>(`/models/discover/${provider}`)
  },

  /**
   * Sync models for a specific provider (discover and register)
   */
  syncProvider: async (provider: string) => {
    return post<ProviderSyncResult>(`/models/sync/${provider}`)
  },

  /**
   * Sync models for all configured providers
   */
  syncAll: async () => {
    return post<AllProvidersSyncResult>('/models/sync')
  },

  /**
   * Get count of registered models for a provider
   */
  getProviderModelCount: async (provider: string) => {
    return get<ProviderModelCount>(`/models/count/${provider}`)
  },

  /**
   * Get all models for a specific provider
   */
  getByProvider: async (provider: string) => {
    return get<Model[]>(`/models/by-provider/${provider}`)
  },

  /**
   * Auto-assign default models based on available models
   */
  autoAssign: async () => {
    return post<AutoAssignResult>('/models/auto-assign')
  },

  /**
   * Test an individual model configuration
   */
  testModel: async (modelId: string): Promise<ModelTestResult> => {
    return post<ModelTestResult>(`/models/${modelId}/test`)
  },
}
