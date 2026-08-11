// ── Settings Store ──────────────────────────────
import { create } from 'zustand'
import type { Theme, Permission, Language } from '@/types'
import { DEFAULT_MODEL, DEFAULT_PERMISSION, DEFAULT_THEME, DEFAULT_LANGUAGE } from '@/lib/constants'
import { api } from '@/lib/api'

interface SettingsState {
  model: string
  permission: Permission
  theme: Theme
  language: Language
  feishuConfigured: boolean
  feishuAppId: string
  feishuHint: string

  // Actions
  setModel: (model: string) => void
  setPermission: (mode: Permission) => void
  setTheme: (theme: Theme) => void
  setLanguage: (lang: Language) => void
  fetchFeishuStatus: () => Promise<void>
  hydrate: () => void
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  model: DEFAULT_MODEL,
  permission: DEFAULT_PERMISSION,
  theme: DEFAULT_THEME,
  language: DEFAULT_LANGUAGE,
  feishuConfigured: false,
  feishuAppId: '',
  feishuHint: '',

  setModel: (model) => {
    set({ model })
    // Also persist + sync to backend
    localStorage.setItem('mai-model', model)
    api.setModel(model).catch(() => {})
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

  hydrate: () => {
    const model = localStorage.getItem('mai-model') || DEFAULT_MODEL
    const perm = (localStorage.getItem('mai-perm') as Permission) || DEFAULT_PERMISSION
    const theme = (localStorage.getItem('mai-theme') as Theme) || DEFAULT_THEME
    const lang = (localStorage.getItem('mai-lang') as Language) || DEFAULT_LANGUAGE
    set({ model, permission: perm, theme, language: lang })
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
