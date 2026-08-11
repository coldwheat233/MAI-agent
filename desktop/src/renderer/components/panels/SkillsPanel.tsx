import { useEffect } from 'react'
import { useSkillStore } from '@/stores/skillStore'
import { Zap, Info } from 'lucide-react'

export function SkillsPanel() {
  const skills = useSkillStore((s) => s.skills)
  const fetchSkills = useSkillStore((s) => s.fetchSkills)

  useEffect(() => {
    fetchSkills()
  }, [])

  return (
    <div className="flex flex-col">
      {skills.length === 0 ? (
        <div className="px-4 py-8 text-center text-xs text-[var(--text3)]">
          <Zap size={24} className="mx-auto mb-2 text-[var(--border)]" />
          No skills loaded
        </div>
      ) : (
        skills.map((skill) => (
          <div
            key={skill.name}
            className="px-4 py-3 border-b border-[var(--border)] hover:bg-[var(--surface2)] transition-colors"
          >
            <div className="flex items-center gap-2 mb-1">
              <Zap size={14} className="text-[var(--accent)] shrink-0" />
              <span className="text-[13px] font-semibold text-[var(--text)]">{skill.name}</span>
            </div>
            <p className="text-[11px] text-[var(--text2)] ml-6 mb-1">{skill.description}</p>
            {skill.whenToUse && (
              <div className="flex items-start gap-1.5 ml-6 text-[10px] text-[var(--text3)]">
                <Info size={11} className="shrink-0 mt-0.5" />
                <span>{skill.whenToUse}</span>
              </div>
            )}
            <div className="ml-6 mt-1.5 flex items-center gap-2">
              <span className="text-[10px] text-[var(--text3)] font-mono">Source: {skill.source}</span>
            </div>
          </div>
        ))
      )}
    </div>
  )
}
