import type { SessionInfo } from '@/types'
import { MessageSquare } from 'lucide-react'

interface SessionItemProps {
  session: SessionInfo
  isActive: boolean
  onClick: () => void
}

export function SessionItem({ session, isActive, onClick }: SessionItemProps) {
  const timeStr = session.updated_at
    ? new Date(session.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : ''

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2.5 rounded-lg transition-colors group ${
        isActive
          ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
          : 'text-[var(--text2)] hover:bg-[var(--surface2)] hover:text-[var(--text)]'
      }`}
    >
      <div className="flex items-center gap-2">
        <MessageSquare size={14} className={`shrink-0 ${isActive ? 'text-[var(--accent)]' : 'text-[var(--text3)]'}`} />
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-medium truncate">{session.title || session.session_id}</div>
          <div className="flex items-center gap-2 text-[10px] text-[var(--text3)]">
            {timeStr && <span>{timeStr}</span>}
            <span>{session.message_count} msgs</span>
          </div>
        </div>
      </div>
    </button>
  )
}
