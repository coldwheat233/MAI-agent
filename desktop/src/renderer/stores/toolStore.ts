// ── Tool Store ──────────────────────────────────
import { create } from 'zustand'
import type { ToolDefinition } from '@/types'
import { api } from '@/lib/api'

interface ToolState {
  tools: ToolDefinition[]
  toolNames: string[]

  fetchTools: () => Promise<void>
  setTools: (names: string[]) => void
}

export const useToolStore = create<ToolState>((set) => ({
  tools: [],
  toolNames: [],

  fetchTools: async () => {
    try {
      const tools = await api.fetchTools()
      set({ tools, toolNames: tools.map((t) => t.name) })
    } catch {
      // Will be populated by WS 'ready' event
    }
  },

  setTools: (names) => set({ toolNames: names }),
}))
