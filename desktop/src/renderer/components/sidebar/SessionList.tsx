import { useState, useMemo } from 'react'
import { Search } from 'lucide-react'
import { useSessionStore } from '@/stores/sessionStore'
import { useChatStore } from '@/stores/chatStore'
import { SessionItem } from './SessionItem'
import { api } from '@/lib/api'

export function SessionList() {
  const [search, setSearch] = useState(false)
  const [query, setQuery] = useState('')
  const sessions = useSessionStore((s) => s.sessions)
  const currentId = useSessionStore((s) => s.currentSessionId)
  const setCurrentSessionId = useSessionStore((s) => s.setCurrentSessionId)
  const setMessages = useChatStore((s) => s.setMessages)

  const filtered = useMemo(() => {
    if (!query.trim()) return sessions
    const q = query.toLowerCase()
    return sessions.filter((s) => s.session_id.toLowerCase().includes(q))
  }, [sessions, query])

  const handleClick = async (sessionId: string) => {
    setCurrentSessionId(sessionId)
    try {
      const detail = await api.fetchSession(sessionId)
      if (detail.messages) {
        const msgs = detail.messages
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((m, i) => ({
            id: `hist_${sessionId}_${i}`,
            role: m.role as 'user' | 'assistant',
            content: m.content || '',
            timestamp: Date.now() - (detail.messages.length - i) * 1000,
            toolCalls: (m.tool_calls || []).map((tc, j) => ({
              id: `hist_tc_${i}_${j}`,
              name: tc.name,
              args: tc.args,
              status: 'ok' as const,
            })),
          }))
        setMessages(msgs)
      }
    } catch {
      // ignore
    }
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Search toggle */}
      <div className="px-3 py-2 flex items-center gap-2">
        {search ? (
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sessions..."
            className="flex-1 bg-[var(--bg)] border border-[var(--border)] rounded-md px-2 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)]"
            autoFocus
            onBlur={() => { if (!query) setSearch(false) }}
            onKeyDown={(e) => { if (e.key === 'Escape') { setSearch(false); setQuery('') } }}
          />
        ) : (
          <>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--text3)] flex-1">Sessions</span>
            <button
              onClick={() => setSearch(true)}
              className="p-1 rounded hover:bg-[var(--surface2)] text-[var(--text3)] hover:text-[var(--text2)]"
            >
              <Search size={13} />
            </button>
          </>
        )}
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-1.5 pb-2 space-y-0.5">
        {filtered.length === 0 ? (
          <div className="px-3 py-4 text-[11px] text-[var(--text3)] text-center">
            {search ? 'No matching sessions' : 'No sessions yet'}
          </div>
        ) : (
          filtered.map((s) => (
            <SessionItem
              key={s.session_id}
              session={s}
              isActive={s.session_id === currentId}
              onClick={() => handleClick(s.session_id)}
            />
          ))
        )}
      </div>
    </div>
  )
}
