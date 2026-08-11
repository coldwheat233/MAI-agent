import { Brain, BookOpen, GitBranch, Settings, PanelLeftClose, PanelLeft } from 'lucide-react'
import { useUIStore } from '@/stores/uiStore'

interface SidebarIconBarProps {
  collapsed: boolean
}

export function SidebarIconBar({ collapsed }: SidebarIconBarProps) {
  const activePanel = useUIStore((s) => s.activePanel)
  const openPanel = useUIStore((s) => s.openPanel)
  const closePanel = useUIStore((s) => s.closePanel)
  const toggleSidebar = useUIStore((s) => s.toggleSidebar)
  const openSettings = useUIStore((s) => s.openSettings)

  const iconClass = (panel: string) =>
    `p-1.5 rounded-md transition-colors ${
      activePanel === panel
        ? 'text-[var(--accent)] bg-[var(--accent)]/10'
        : 'text-[var(--text3)] hover:text-[var(--text2)] hover:bg-[var(--surface2)]'
    }`

  const handlePanelToggle = (panel: 'memory' | 'skills' | 'git') => {
    if (activePanel === panel) {
      closePanel()
    } else {
      openPanel(panel)
    }
  }

  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-2 px-2 py-2 border-t border-[var(--border)]">
        <button onClick={toggleSidebar} className="p-1.5 rounded-md text-[var(--text3)] hover:text-[var(--text2)] hover:bg-[var(--surface2)]" title="Expand sidebar">
          <PanelLeft size={16} />
        </button>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1 px-3 py-2 border-t border-[var(--border)]">
      <button
        onClick={() => handlePanelToggle('memory')}
        className={iconClass('memory')}
        title="Memory"
      >
        <Brain size={16} />
      </button>
      <button
        onClick={() => handlePanelToggle('skills')}
        className={iconClass('skills')}
        title="Skills"
      >
        <BookOpen size={16} />
      </button>
      <button
        onClick={() => handlePanelToggle('git')}
        className={iconClass('git')}
        title="Git"
      >
        <GitBranch size={16} />
      </button>
      <button
        onClick={openSettings}
        className="p-1.5 rounded-md text-[var(--text3)] hover:text-[var(--text2)] hover:bg-[var(--surface2)] ml-auto"
        title="Settings"
      >
        <Settings size={16} />
      </button>
      <button
        onClick={toggleSidebar}
        className="p-1.5 rounded-md text-[var(--text3)] hover:text-[var(--text2)] hover:bg-[var(--surface2)]"
        title="Collapse sidebar"
      >
        <PanelLeftClose size={16} />
      </button>
    </div>
  )
}
