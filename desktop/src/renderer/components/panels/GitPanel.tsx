import { useEffect } from 'react'
import { useGitStore } from '@/stores/gitStore'
import { GitBranch, GitCommit, RefreshCw } from 'lucide-react'
import { useWSStore } from '@/stores/wsStore'

export function GitPanel() {
  const { isRepo, branch, status, recentCommits, loading, fetchGitStatus } = useGitStore()
  const send = useWSStore((s) => s.send)

  useEffect(() => {
    fetchGitStatus()
    const interval = setInterval(fetchGitStatus, 30000)
    return () => clearInterval(interval)
  }, [])

  if (!isRepo) {
    return (
      <div className="px-4 py-8 text-center text-xs text-[var(--text3)]">
        <GitBranch size={24} className="mx-auto mb-2 text-[var(--border)]" />
        Not a git repository
      </div>
    )
  }

  const handleAction = (command: string) => {
    send({ type: 'submit', text: command })
  }

  const statusLines = status ? status.split('\n').filter(Boolean) : []

  return (
    <div className="flex flex-col">
      {/* Branch header */}
      <div className="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranch size={15} className="text-[var(--green)]" />
          <span className="text-sm font-semibold font-mono text-[var(--green)]">{branch}</span>
        </div>
        <button
          onClick={fetchGitStatus}
          disabled={loading}
          className="p-1.5 rounded-md hover:bg-[var(--surface2)] text-[var(--text3)] hover:text-[var(--text)] disabled:opacity-50"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Status */}
      <div className="px-4 py-3 border-b border-[var(--border)]">
        <h4 className="text-[10px] font-bold uppercase tracking-wider text-[var(--text3)] mb-2">Status</h4>
        {statusLines.length === 0 ? (
          <div className="text-xs text-[var(--green)]">Working tree clean</div>
        ) : (
          <div className="space-y-0.5">
            {statusLines.slice(0, 10).map((line, i) => (
              <div key={i} className="text-[11px] font-mono text-[var(--text2)]">
                {line}
              </div>
            ))}
            {statusLines.length > 10 && (
              <div className="text-[10px] text-[var(--text3)]">+{statusLines.length - 10} more</div>
            )}
          </div>
        )}
      </div>

      {/* Quick actions */}
      <div className="px-4 py-3 border-b border-[var(--border)] space-y-1.5">
        <h4 className="text-[10px] font-bold uppercase tracking-wider text-[var(--text3)] mb-2">Actions</h4>
        <button
          onClick={() => handleAction('git status')}
          className="w-full text-left px-3 py-1.5 rounded-md text-[11px] text-[var(--text2)] hover:bg-[var(--surface2)] hover:text-[var(--text)] transition-colors"
        >
          📋 git status
        </button>
        <button
          onClick={() => handleAction('git diff')}
          className="w-full text-left px-3 py-1.5 rounded-md text-[11px] text-[var(--text2)] hover:bg-[var(--surface2)] hover:text-[var(--text)] transition-colors"
        >
          📊 git diff
        </button>
        <button
          onClick={() => handleAction('git add -A && git commit -m "update"')}
          className="w-full text-left px-3 py-1.5 rounded-md text-[11px] text-[var(--text2)] hover:bg-[var(--surface2)] hover:text-[var(--text)] transition-colors"
        >
          💾 Stage & Commit
        </button>
        <button
          onClick={() => handleAction('git push')}
          className="w-full text-left px-3 py-1.5 rounded-md text-[11px] text-[var(--text2)] hover:bg-[var(--surface2)] hover:text-[var(--text)] transition-colors"
        >
          🚀 git push
        </button>
      </div>

      {/* Recent commits */}
      <div className="px-4 py-3">
        <h4 className="text-[10px] font-bold uppercase tracking-wider text-[var(--text3)] mb-2">Recent Commits</h4>
        {recentCommits ? (
          <div className="space-y-1">
            {recentCommits.split('\n').slice(0, 5).map((line, i) => (
              <div key={i} className="flex items-start gap-1.5 text-[11px] font-mono text-[var(--text2)]">
                <GitCommit size={12} className="shrink-0 mt-0.5 text-[var(--text3)]" />
                <span className="truncate">{line}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[11px] text-[var(--text3)]">No commits yet</div>
        )}
      </div>
    </div>
  )
}
