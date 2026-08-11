import { useChatStore } from '@/stores/chatStore'
import { useSettingsStore } from '@/stores/settingsStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useWSStore } from '@/stores/wsStore'
import { Wifi, WifiOff } from 'lucide-react'

export function StatusBar() {
  const tokens = useChatStore((s) => s.tokensUsed)
  const ctxTokens = useChatStore((s) => s.contextTokens)
  const turnCount = useChatStore((s) => s.turnCount)
  const toolCount = useChatStore((s) => s.toolCallCount)
  const model = useSettingsStore((s) => s.model)
  const wsStatus = useWSStore((s) => s.status)
  const wsName = useWorkspaceStore((s) => s.name)

  const tokenStr = tokens > 0 ? `${tokens}/${Math.round(ctxTokens / 1000)}K` : '—'

  return (
    <div className="h-7 px-4 bg-[var(--surface2)] border-t border-[var(--border)] flex items-center gap-3 text-[11px] text-[var(--text3)] select-none shrink-0">
      <span className="font-medium text-[var(--text2)]">{wsName}</span>
      <span className="text-[var(--border)]">|</span>
      <span>{model}</span>
      <span className="text-[var(--border)]">|</span>
      <span>Tokens: {tokenStr}</span>
      {turnCount > 0 && (
        <>
          <span className="text-[var(--border)]">|</span>
          <span>Turn {turnCount} · Tools {toolCount}</span>
        </>
      )}
      <span className="flex-1" />
      {wsStatus === 'connected' ? (
        <Wifi size={12} className="text-[var(--green)]" />
      ) : (
        <WifiOff size={12} className="text-[var(--red)]" />
      )}
    </div>
  )
}
