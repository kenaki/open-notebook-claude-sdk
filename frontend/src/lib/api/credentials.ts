import { get, post, put, del } from './client'

// Types for credentials API
export interface Credential {
  id: string
  name: string
  provider: string
  modalities: string[]
  base_url?: string | null
  endpoint?: string | null
  api_version?: string | null
  endpoint_llm?: string | null
  endpoint_embedding?: string | null
  endpoint_stt?: string | null
  endpoint_tts?: string | null
  project?: string | null
  location?: string | null
  credentials_path?: string | null
  num_ctx?: number | null
  has_api_key: boolean
  created: string
  updated: string
  model_count: number
  decryption_error?: string | null
}

export interface CreateCredentialRequest {
  name: string
  provider: string
  modalities: string[]
  api_key?: string
  base_url?: string
  endpoint?: string
  api_version?: string
  endpoint_llm?: string
  endpoint_embedding?: string
  endpoint_stt?: string
  endpoint_tts?: string
  project?: string
  location?: string
  credentials_path?: string
  num_ctx?: number | null
}

export interface UpdateCredentialRequest {
  name?: string
  modalities?: string[]
  api_key?: string
  base_url?: string
  endpoint?: string
  api_version?: string
  endpoint_llm?: string
  endpoint_embedding?: string
  endpoint_stt?: string
  endpoint_tts?: string
  project?: string
  location?: string
  credentials_path?: string
  num_ctx?: number | null
}

export interface DiscoveredModel {
  name: string
  provider: string
  model_type?: string
  description?: string
}

export interface RegisterModelData {
  name: string
  provider: string
  model_type: string
}

export interface DiscoverModelsResponse {
  credential_id: string
  provider: string
  discovered: DiscoveredModel[]
}

export interface RegisterModelsRequest {
  models: RegisterModelData[]
}

export interface RegisterModelsResponse {
  created: number
  existing: number
}

export interface TestConnectionResult {
  provider: string
  success: boolean
  message: string
}

export interface CredentialDeleteResponse {
  message: string
  deleted_models: number
}

export interface MigrationResult {
  message: string
  migrated: string[]
  skipped: string[]
  not_configured?: string[]
  errors: string[]
}

export interface CredentialStatus {
  configured: Record<string, boolean>
  source: Record<string, string>
  encryption_configured: boolean
}

export type EnvStatus = Record<string, boolean>

export const credentialsApi = {
  /**
   * Get configuration status for all providers
   */
  getStatus: async (): Promise<CredentialStatus> => {
    return get<CredentialStatus>('/credentials/status')
  },

  /**
   * Get environment variable status for all providers
   */
  getEnvStatus: async (): Promise<EnvStatus> => {
    return get<EnvStatus>('/credentials/env-status')
  },

  /**
   * List all credentials, optionally filtered by provider
   */
  list: async (provider?: string): Promise<Credential[]> => {
    const params = provider ? { provider } : {}
    return get<Credential[]>('/credentials', { params })
  },

  /**
   * List credentials for a specific provider
   */
  listByProvider: async (provider: string): Promise<Credential[]> => {
    return get<Credential[]>(`/credentials/by-provider/${provider}`)
  },

  /**
   * Get a specific credential by ID
   */
  get: async (credentialId: string): Promise<Credential> => {
    return get<Credential>(`/credentials/${credentialId}`)
  },

  /**
   * Create a new credential
   */
  create: async (data: CreateCredentialRequest): Promise<Credential> => {
    return post<Credential>('/credentials', data)
  },

  /**
   * Update an existing credential
   */
  update: async (credentialId: string, data: UpdateCredentialRequest): Promise<Credential> => {
    return put<Credential>(`/credentials/${credentialId}`, data)
  },

  /**
   * Delete a credential
   */
  delete: async (
    credentialId: string,
    options?: { delete_models?: boolean; migrate_to?: string }
  ): Promise<CredentialDeleteResponse> => {
    const params: Record<string, string | boolean> = {}
    if (options?.delete_models) params.delete_models = true
    if (options?.migrate_to) params.migrate_to = options.migrate_to
    return del<CredentialDeleteResponse>(`/credentials/${credentialId}`, { params })
  },

  /**
   * Test connection for a credential
   */
  test: async (credentialId: string): Promise<TestConnectionResult> => {
    return post<TestConnectionResult>(`/credentials/${credentialId}/test`)
  },

  /**
   * Discover models using a credential's API key
   */
  discover: async (credentialId: string): Promise<DiscoverModelsResponse> => {
    return post<DiscoverModelsResponse>(`/credentials/${credentialId}/discover`)
  },

  /**
   * Register discovered models and link them to a credential
   */
  registerModels: async (
    credentialId: string,
    data: RegisterModelsRequest
  ): Promise<RegisterModelsResponse> => {
    return post<RegisterModelsResponse>(`/credentials/${credentialId}/register-models`, data)
  },

  /**
   * Migrate from ProviderConfig to individual credentials
   */
  migrateFromProviderConfig: async (): Promise<MigrationResult> => {
    return post<MigrationResult>('/credentials/migrate-from-provider-config')
  },

  /**
   * Migrate from environment variables to credentials
   */
  migrateFromEnv: async (): Promise<MigrationResult> => {
    return post<MigrationResult>('/credentials/migrate-from-env')
  },
}
