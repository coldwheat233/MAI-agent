// ── Session Store ───────────────────────────────
import { create } from 'zustand'
import type { SessionInfo } from '@/types'
import { api } from '@/lib/api'

interface SessionState {
  sessions: SessionInfo[]
  loadingSessions: boolean
  // Workspace-grouped sessions: { workspacePath: SessionInfo[] }
  workspaceSessions: Record<string, SessionInfo[]>
  currentSessionId: string

  fetchSessions: () => Promise<void>
  fetchAllWorkspaceSessions: (workspaces: string[]) => Promise<void>
  newSession: () => Promise<void>
  setCurrentSessionId: (id: string) => void
  deleteSession: (id: string) => Promise<boolean>
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  loadingSessions: false,
  workspaceSessions: {},
  currentSessionId: 'default',

  fetchSessions: async () => {
    set({ loadingSessions: true })
    try {
      const sessions = await api.fetchSessions()
      set({ sessions: Array.isArray(sessions) ? sessions : [] })
    } catch {
      // Non-critical — 保留旧值
    } finally {
      set({ loadingSessions: false })
    }
  },

  fetchAllWorkspaceSessions: async (workspaces: string[]) => {
    const result: Record<string, SessionInfo[]> = {}
    for (const ws of workspaces) {
      try {
        // Switch to workspace to fetch its sessions
        const res = await fetch(`http://localhost:8765/api/sessions?workspace=${encodeURIComponent(ws)}`)
        if (res.ok) {
          result[ws] = await res.json()
        }
      } catch {
        result[ws] = []
      }
    }
    set({ workspaceSessions: result })
  },

  newSession: async () => {
    try {
      const result = await api.restartEngine()
      set({ currentSessionId: result.session_id })
    } catch {
      // Non-critical
    }
  },

  setCurrentSessionId: (id) => set({ currentSessionId: id }),

  deleteSession: async (id) => {
    try {
      const res = await fetch(`http://localhost:8765/api/sessions/${id}`, { method: 'DELETE' })
      if (res.ok) {
        // Remove from local state
        set((s) => ({
          sessions: s.sessions.filter((x) => x.session_id !== id),
        }))
        return true
      }
      return false
    } catch {
      return false
    }
  },
}))
