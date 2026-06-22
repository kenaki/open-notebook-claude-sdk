export interface Model {
  id: string
  name: string
  provider: string
  type: 'language' | 'embedding' | 'text_to_speech' | 'speech_to_text'
  credential?: string | null
  created: string
  updated: string
}

export interface CreateModelRequest {
  name: string
  provider: string
  type: 'language' | 'embedding' | 'text_to_speech' | 'speech_to_text'
  credential?: string
}

export interface ModelDefaults {
  default_chat_model?: string | null
  default_transformation_model?: string | null
  large_context_model?: string | null
  default_text_to_speech_model?: string | null
  default_speech_to_text_model?: string | null
  default_embedding_model?: string | null
  default_tools_model?: string | null
}

export interface ProviderAvailability {
  available: string[]
  unavailable: string[]
  supported_types: Record<string, string[]>
}

// Model Discovery Types
export interface DiscoveredModel {
  name: string
  provider: string
  model_type: 'language' | 'embedding' | 'text_to_speech' | 'speech_to_text'
  description?: string
}

export interface ProviderSyncResult {
  provider: string
  discovered: number
  new: number
  existing: number
}

export interface AllProvidersSyncResult {
  results: Record<string, ProviderSyncResult>
  total_discovered: number
  total_new: number
}

export interface ProviderModelCount {
  provider: string
  counts: Record<string, number>
  total: number
}

export interface AutoAssignResult {
  assigned: Record<string, string>  // slot_name -> model_id
  skipped: string[]  // slots already assigned
  missing: string[]  // slots with no available models
}

export interface ModelTestResult {
  success: boolean
  message: string
  details?: string
}

export interface ClaudeAgentModelOption {
  value: string  // '' = follow Claude Code default
  label: string
}

export interface ClaudeAgentModelConfig {
  model?: string | null         // pinned model id (null = follow CC default)
  env_override?: string | null  // CLAUDE_AGENT_MODEL env value (read-only)
  options: ClaudeAgentModelOption[]
}

export interface UpdateClaudeAgentModelRequest {
  model?: string | null  // empty/null follows the Claude Code default
}