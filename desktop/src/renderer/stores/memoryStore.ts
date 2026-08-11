// ── Memory Store ────────────────────────────────
import { create } from 'zustand'
import type { TaggedMemory } from '@/types'
import { api } from '@/lib/api'

interface MemoryState {
  memories: TaggedMemory[]
  tags: string[]
  selectedTag: string | null
  selectedMemory: TaggedMemory | null
  searchQuery: string

  fetchMemories: () => Promise<void>
  selectTag: (tag: string | null) => void
  selectMemory: (memory: TaggedMemory | null) => void
  setSearchQuery: (q: string) => void
  // Derived in component: filteredMemories
}

export const useMemoryStore = create<MemoryState>((set) => ({
  memories: [],
  tags: [],
  selectedTag: null,
  selectedMemory: null,
  searchQuery: '',

  fetchMemories: async () => {
    try {
      const data = await api.fetchMemories()
      set({
        memories: data.memories || [],
        tags: data.tags || [],
      })
    } catch {
      // Non-critical
    }
  },

  selectTag: (tag) => set({ selectedTag: tag, selectedMemory: null }),

  selectMemory: (memory) => set({ selectedMemory: memory }),

  setSearchQuery: (q) => set({ searchQuery: q }),
}))
