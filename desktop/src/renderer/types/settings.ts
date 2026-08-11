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
