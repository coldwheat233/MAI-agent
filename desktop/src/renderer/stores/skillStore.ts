// ── Skill Store ─────────────────────────────────
import { create } from 'zustand'
import type { SkillInfo } from '@/types'
import { api } from '@/lib/api'

interface SkillState {
  skills: SkillInfo[]

  fetchSkills: () => Promise<void>
}

export const useSkillStore = create<SkillState>((set) => ({
  skills: [],

  fetchSkills: async () => {
    try {
      const skills = await api.fetchSkills()
      set({ skills: Array.isArray(skills) ? skills : [] })
    } catch {
      // Non-critical
    }
  },
}))
