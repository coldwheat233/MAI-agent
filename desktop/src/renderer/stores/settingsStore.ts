// ── Settings Store ──────────────────────────────
import { create } from 'zustand'
import type { Theme, Permission, Language, ProviderInfo } from '@/types'
import { DEFAULT_MODEL, DEFAULT_PERMISSION, DEFAULT_THEME, DEFAULT_LANGUAGE } from '@/lib/constants'
import { api } from '@/lib/api'

interface SettingsState {
  model: string
  provider: string
  providers: ProviderInfo[]
  permission: Permission
  theme: Theme
  language: Language
  feishuConfigured: boolean
  feishuAppId: string
  feishuHint: string

  // Actions
  setModel: (model: string, provider?: string) => void
  setModelFromServer: (model: string) => void
  setPermission: (mode: Permission) => void
  setTheme: (theme: Theme) => void
  setLanguage: (lang: Language) => void
  fetchFeishuStatus: () => Promise<void>
  fetchProviders: () => Promise<void>
  hydrate: () => void
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  model: DEFAULT_MODEL,
  provider: 'deepseek',
  providers: [],
  permission: DEFAULT_PERMISSION,
  theme: DEFAULT_THEME,
  language: DEFAULT_LANGUAGE,
  feishuConfigured: false,
  feishuAppId: '',
  feishuHint: '',

  setModel: (model, provider) => {
    set({ model, provider: provider || get().provider })
    // Also persist + sync to backend（热切换，不重建引擎）
    localStorage.setItem('mai-model', model)
    if (provider) localStorage.setItem('mai-provider', provider)
    api.setModel(model, provider || get().provider).catch(() => {})
  },

  setModelFromServer: (model) => {
    // 后端 ready 回显当前 model：只更新本地显示，不回 POST /api/model。
    // 否则每次 WS 连接/重连都会触发 /api/model → 重建引擎 → 换新 session_id，丢上下文。
    set({ model })
    localStorage.setItem('mai-model', model)
  },

  setPermission: (mode) => {
    set({ permission: mode })
    localStorage.setItem('mai-perm', mode)
    api.setMode(mode).catch(() => {})
  },

  setTheme: (theme) => {
    set({ theme })
    localStorage.setItem('mai-theme', theme)
    applyTheme(theme)
  },

  setLanguage: (lang) => {
    set({ language: lang })
    localStorage.setItem('mai-lang', lang)
  },

  fetchFeishuStatus: async () => {
    try {
      const status = await api.fetchFeishuStatus()
      set({
        feishuConfigured: status.configured,
        feishuAppId: status.app_id || '',
        feishuHint: status.hint || '',
      })
    } catch {
      // Feishu is optional
    }
  },

  fetchProviders: async () => {
    try {
      const resp = await api.fetchProviders()
      set({
        providers: resp.providers,
        provider: resp.current || 'deepseek',
        model: resp.current_model || resp.providers.find((p: ProviderInfo) => p.active)?.default_model || DEFAULT_MODEL,
      })
    } catch {
      // 后端不可达时保持默认
    }
  },

  hydrate: () => {
    const model = localStorage.getItem('mai-model') || DEFAULT_MODEL
    const provider = localStorage.getItem('mai-provider') || 'deepseek'
    const perm = (localStorage.getItem('mai-perm') as Permission) || DEFAULT_PERMISSION
    const theme = (localStorage.getItem('mai-theme') as Theme) || DEFAULT_THEME
    const lang = (localStorage.getItem('mai-lang') as Language) || DEFAULT_LANGUAGE
    set({ model, provider, permission: perm, theme, language: lang })
    applyTheme(theme)
  },
}))

// ── Theme Application ───────────────────────────

export function applyTheme(theme: Theme) {
  const resolved = theme === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : theme

  document.documentElement.setAttribute('data-theme', resolved)

  // Also toggle Tailwind dark class
  if (resolved === 'dark') {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

export function resolveTheme(theme: Theme): 'dark' | 'light' {
  if (theme === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return theme
}
