// ── Git Store ───────────────────────────────────
import { create } from 'zustand'
import type { GitStatus } from '@/types'
import { api } from '@/lib/api'

interface GitState {
  isRepo: boolean
  branch: string
  status: string
  recentCommits: string
  loading: boolean

  fetchGitStatus: () => Promise<void>
}

export const useGitStore = create<GitState>((set) => ({
  isRepo: false,
  branch: '',
  status: '',
  recentCommits: '',
  loading: false,

  fetchGitStatus: async () => {
    set({ loading: true })
    try {
      const data = await api.fetchGitStatus()
      set({
        isRepo: data.is_repo,
        branch: data.branch,
        status: data.status,
        recentCommits: data.recent_commits,
        loading: false,
      })
    } catch {
      set({ isRepo: false, loading: false })
    }
  },
}))
