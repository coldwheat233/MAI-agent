import type { Command } from '@/hooks/useCommandMenu'

interface CommandMenuProps {
  isOpen: boolean
  commands: Command[]
  selectedIndex: number
}

export function CommandMenu({ isOpen, commands, selectedIndex }: CommandMenuProps) {
  if (!isOpen) return null

  return (
    <div className="absolute z-40 bottom-full mb-2 left-0 w-64 bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-xl overflow-hidden animate-fade-in">
      {commands.map((cmd, i) => (
        <div
          key={cmd.id}
          className={`flex items-center gap-3 px-3 py-2.5 text-sm cursor-pointer ${
            i === selectedIndex
              ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
              : 'text-[var(--text2)] hover:bg-[var(--surface2)] hover:text-[var(--text)]'
          }`}
        >
          <span className="text-xs font-mono font-semibold text-[var(--accent)] w-16 shrink-0">
            {cmd.label}
          </span>
          <span className="text-xs truncate">{cmd.description}</span>
        </div>
      ))}
    </div>
  )
}
