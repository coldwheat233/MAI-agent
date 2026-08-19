// ── Settings Types ──────────────────────────────

export type Theme = 'dark' | 'light' | 'system'
export type Permission = 'auto' | 'manual' | 'plan'
export type Language = 'zh' | 'en'

export interface Settings {
  model: string
  permission: Permission
  theme: Theme
  language: Language
  feishuConfigured: boolean
  feishuAppId: string
}

export interface FeishuStatus {
  configured: boolean
  app_id: string
  tools_available: boolean
  hint: string
}

export interface CoordinatorState {
  brain: string
  status: string
}

// ── LLM Provider（对齐 DSH listProviders）──────────────

export interface ProviderInfo {
  name: string
  label: string
  base_url: string
  protocol: string
  models: string[]
  default_model: string
  active: boolean
  has_key: boolean
  is_custom: boolean
}

export interface ProvidersResponse {
  current: string
  current_model: string
  protocols: string[]
  providers: ProviderInfo[]
}
