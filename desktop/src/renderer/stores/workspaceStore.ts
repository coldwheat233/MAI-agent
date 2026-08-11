// ── Workspace Store ─────────────────────────────
import { create } from 'zustand'
import type { WorkspaceEntry, BrowseEntry } from '@/types'
import { api } from '@/lib/api'

function normalize(p: string): string {
  return p.replace(/\\/g, '/')
}

interface WorkspaceState {
  cwd: string
  name: string
  workspaces: WorkspaceEntry[]
  browsePath: string
  browseEntries: BrowseEntry[]

  fetchWorkspace: () => Promise<void>
  fetchWorkspaces: () => Promise<void>
  switchWorkspace: (cwd: string) => Promise<void>
  addWorkspace: (cwd: string) => Promise<void>
  removeWorkspace: (cwd: string) => Promise<void>
  browseDirectory: (path: string) => Promise<void>
  setCwd: (cwd: string) => void
}

// 工作区列表权威来源是后端 SQLite（mai.db → /api/workspaces）。
// 不再用浏览器 localStorage：跨 origin / 重启 / 桌面 vs 网页端全共享。
export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  cwd: '',
  name: 'Loading...',
  workspaces: [],
  browsePath: '',
  browseEntries: [],

  fetchWorkspace: async () => {
    try {
      const info = await api.fetchWorkspace()
      const name = info.name || info.cwd.split(/[\\/]/).pop() || '...'
      set({ cwd: info.cwd, name })
    } catch {
      set({ name: 'Unknown' })
    }
  },

  fetchWorkspaces: async () => {
    try {
      const ws = await api.fetchWorkspaces()
      set({ workspaces: Array.isArray(ws) ? ws : [] })
    } catch { /* ignore */ }
  },

  switchWorkspace: async (cwd) => {
    const result = await api.switchWorkspace(cwd)
    const name = result.cwd.split(/[\\/]/).pop() || cwd
    set({ cwd: result.cwd, name })
    // 后端 register_workspace 已更新 last_used，拉一次刷新顺序
    get().fetchWorkspaces()
  },

  addWorkspace: async (cwd) => {
    // 调后端 register（POST /api/workspaces/register）—— 不切换当前引擎
    await api.registerWorkspace(cwd)
    get().fetchWorkspaces()
  },

  removeWorkspace: async (cwd) => {
    // 调后端 unregister —— SQLite FK CASCADE 会带走该 workspace 的所有 session
    await api.unregisterWorkspace(cwd)
    get().fetchWorkspaces()
  },

  browseDirectory: async (path) => {
    try {
      const result = await api.browseDirectory(path)
      set({ browsePath: result.path, browseEntries: result.entries })
    } catch { /* ignore */ }
  },

  setCwd: (cwd) => set({ cwd, name: cwd.split(/[\\/]/).pop() || cwd }),
}))
