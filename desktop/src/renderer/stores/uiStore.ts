// ── UI Store ────────────────────────────────────
import { create } from 'zustand'

interface UIState {
  sidebarCollapsed: boolean
  activePanel: 'none' | 'memory' | 'skills' | 'git' | 'learning'
  isSettingsOpen: boolean

  toggleSidebar: () => void
  openPanel: (panel: 'memory' | 'skills' | 'git' | 'learning') => void
  closePanel: () => void
  openSettings: () => void
  closeSettings: () => void
}

export const useUIStore = create<UIState>((set) => ({
  sidebarCollapsed: false,
  activePanel: 'none',
  isSettingsOpen: false,

  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),

  openPanel: (panel) => set({ activePanel: panel }),

  closePanel: () => set({ activePanel: 'none' }),

  openSettings: () => set({ isSettingsOpen: true }),

  closeSettings: () => set({ isSettingsOpen: false }),
}))
