import { X } from 'lucide-react'
import { useUIStore } from '@/stores/uiStore'
import { MemoryPanel } from './MemoryPanel'
import { SkillsPanel } from './SkillsPanel'
import { GitPanel } from './GitPanel'
import { LearningPanel } from './LearningPanel'
import { TracesPanel } from './TracesPanel'

export function PanelContainer() {
  const activePanel = useUIStore((s) => s.activePanel)
  const closePanel = useUIStore((s) => s.closePanel)

  if (activePanel === 'none') return null

  const titles: Record<string, string> = {
    memory: 'Memory',
    skills: 'Skills',
    git: 'Git',
    learning: '学习队列',
    traces: 'Traces',
  }

  return (
    <div className="w-[340px] bg-[var(--surface)] border-l border-[var(--border)] flex flex-col shrink-0 animate-slide-in">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
        <h3 className="text-sm font-semibold text-[var(--text)]">{titles[activePanel]}</h3>
        <button
          onClick={closePanel}
          className="p-1 rounded hover:bg-[var(--surface2)] text-[var(--text3)] hover:text-[var(--text)]"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {activePanel === 'memory' && <MemoryPanel />}
        {activePanel === 'skills' && <SkillsPanel />}
        {activePanel === 'git' && <GitPanel />}
        {activePanel === 'learning' && <LearningPanel />}
        {activePanel === 'traces' && <TracesPanel />}
      </div>
    </div>
  )
}
