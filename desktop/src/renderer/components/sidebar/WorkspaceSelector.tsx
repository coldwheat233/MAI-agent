import { useState } from 'react'
import { Folder, ChevronDown } from 'lucide-react'
import { useWorkspaceStore } from '@/stores/workspaceStore'

interface WorkspaceSelectorProps {
  collapsed: boolean
}

export function WorkspaceSelector({ collapsed }: WorkspaceSelectorProps) {
  const [open, setOpen] = useState(false)
  const name = useWorkspaceStore((s) => s.name)
  const workspaces = useWorkspaceStore((s) => s.workspaces)
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces)
  const switchWorkspace = useWorkspaceStore((s) => s.switchWorkspace)

  if (collapsed) return null

  const handleToggle = () => {
    if (!open) fetchWorkspaces()
    setOpen(!open)
  }

  return (
    <div className="relative">
      <button
        onClick={handleToggle}
        className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-[var(--text2)] hover:text-[var(--text)] hover:bg-[var(--surface2)] rounded-md transition-colors"
      >
        <Folder size={15} className="shrink-0 text-[var(--accent)]" />
        <span className="truncate flex-1 text-left font-medium">{name}</span>
        <ChevronDown size={14} className={`shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute top-full left-0 right-0 z-30 mt-1 bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-lg max-h-[180px] overflow-y-auto animate-fade-in">
          {workspaces.length === 0 ? (
            <div className="px-3 py-2 text-[11px] text-[var(--text3)]">No saved workspaces</div>
          ) : (
            workspaces.map((ws, i) => (
              <button
                key={ws.slug || ws.path || i}
                onClick={() => {
                  const cwd = ws.path || ws.slug || ''
                  if (cwd) switchWorkspace(cwd)
                  setOpen(false)
                }}
                className="w-full text-left px-3 py-2 text-xs text-[var(--text2)] hover:bg-[var(--surface2)] hover:text-[var(--text)] transition-colors truncate"
              >
                📁 {ws.path || ws.slug}
                {ws.session_count !== undefined && (
                  <span className="text-[var(--text3)] ml-2">{ws.session_count} sessions</span>
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
