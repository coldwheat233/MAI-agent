import { useSettingsStore } from '@/stores/settingsStore'
import { useSessionStore } from '@/stores/sessionStore'
import { useChatStore } from '@/stores/chatStore'
import { useWSStore } from '@/stores/wsStore'
import { EXAMPLE_PROMPTS } from '@/lib/constants'
import { Sparkles } from 'lucide-react'
import { api } from '@/lib/api'

interface EmptyStateProps {
  onPromptClick: (text: string) => void
}

export function EmptyState({ onPromptClick }: EmptyStateProps) {
  const lang = useSettingsStore((s) => s.language)
  const sessions = useSessionStore((s) => s.sessions)
  const permission = useSettingsStore((s) => s.permission)

  const prompts = EXAMPLE_PROMPTS[lang === 'zh' ? 'zh' : 'en']

  const recentSessions = sessions.slice(0, 3)

  const handleSessionClick = async (sessionId: string) => {
    try {
      // Load messages into view
      const detail = await api.fetchSession(sessionId)
      if (detail.messages) {
        const msgs = detail.messages.map((m, i) => ({
          id: `hist_${i}`,
          role: m.role === 'user' ? 'user' as const : 'assistant' as const,
          content: m.content || '',
          timestamp: Date.now() - (detail.messages.length - i) * 1000,
        }))
        useChatStore.getState().setMessages(msgs)
      }
    } catch {
      // ignore
    }
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 text-center">
      {/* Logo */}
      <div className="mb-6">
        <div className="w-16 h-16 rounded-2xl bg-[var(--accent)]/10 flex items-center justify-center mx-auto mb-4">
          <Sparkles size={32} className="text-[var(--accent)]" />
        </div>
        <h1 className="text-2xl font-bold text-[var(--text)]">MAI-agent</h1>
        <p className="text-sm text-[var(--text2)] mt-2">
          {lang === 'zh' ? '你的个人 AI 编程助手' : 'Your Personal AI Coding Assistant'}
        </p>
      </div>

      {/* Example prompts */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-2xl w-full mb-10">
        {prompts.map((prompt, i) => (
          <button
            key={i}
            onClick={() => onPromptClick(prompt)}
            className="p-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface2)] hover:border-[var(--text3)] text-sm text-[var(--text2)] hover:text-[var(--text)] text-left transition-all"
          >
            {prompt}
          </button>
        ))}
      </div>

      {/* Recent sessions */}
      {recentSessions.length > 0 && (
        <div className="w-full max-w-md">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text3)] mb-3">
            {lang === 'zh' ? '最近会话' : 'Recent Sessions'}
          </p>
          <div className="space-y-1">
            {recentSessions.map((s) => (
              <button
                key={s.session_id}
                onClick={() => handleSessionClick(s.session_id)}
                className="w-full text-left px-4 py-2.5 rounded-lg hover:bg-[var(--surface2)] text-sm text-[var(--text2)] hover:text-[var(--text)] transition-colors"
              >
                <span className="font-mono text-xs text-[var(--accent)]">{s.session_id}</span>
                <span className="text-[var(--text3)] ml-3">{s.message_count} msgs</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
