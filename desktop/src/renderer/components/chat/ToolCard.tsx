import { useState } from 'react'
import { ChevronRight, Wrench, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import type { ToolCallCard as ToolCallCardType } from '@/types'

interface ToolCardProps {
  tool: ToolCallCardType
}

export function ToolCard({ tool }: ToolCardProps) {
  const [expanded, setExpanded] = useState(false)
  const { name, args, result, status, isError } = tool
  const safeArgs = args || '{}'

  const statusIcon = status === 'running'
    ? <Loader2 size={14} className="animate-spin text-[var(--yellow)]" />
    : status === 'ok'
    ? <CheckCircle size={14} className="text-[var(--green)]" />
    : <XCircle size={14} className="text-[var(--red)]" />

  const statusClass = status === 'running'
    ? 'border-l-[var(--yellow)] animate-breathe'
    : status === 'ok'
    ? 'border-l-[var(--green)]'
    : 'border-l-[var(--red)]'

  return (
    <div className={`my-1 bg-[var(--tool-bg)] border-l-[3px] rounded-r-lg overflow-hidden max-w-[75%] animate-fade-in cursor-pointer ${statusClass}`}>
      <button
        onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-[var(--surface2)] transition-colors text-left"
      >
        <ChevronRight
          size={14}
          className={`text-[var(--text3)] transition-transform shrink-0 ${expanded ? 'rotate-90' : ''}`}
        />
        <Wrench size={14} className="text-[var(--accent)] shrink-0" />
        <span className="text-[13px] font-semibold text-[var(--accent)] shrink-0">{name}</span>
        <span className="text-[12px] text-[var(--text2)] font-mono truncate flex-1 min-w-0">
          {safeArgs.length > 60 ? safeArgs.slice(0, 60) + '...' : safeArgs}
        </span>
        <span className="shrink-0">{statusIcon}</span>
      </button>

      {expanded && (
        <div className="border-t border-[var(--border)] animate-fade-in">
          {safeArgs !== '{}' && (
            <div className="px-3 py-2 text-[11px] font-mono text-[var(--text3)] border-b border-[var(--border)]">
              <span className="text-[10px] font-semibold uppercase tracking-wider">Args: </span>
              {safeArgs}
            </div>
          )}
          {result ? (
            <pre className={`p-3 text-[12px] font-mono whitespace-pre-wrap max-h-60 overflow-y-auto ${isError ? 'text-[var(--red)]' : 'text-[var(--text2)]'}`}>
              {(result || '').length > 3000 ? result.slice(0, 3000) + '\n... (truncated)' : result}
            </pre>
          ) : status === 'running' ? (
            <div className="p-3 text-[12px] text-[var(--text3)] flex items-center gap-2">
              <Loader2 size={12} className="animate-spin" />
              Running...
            </div>
          ) : (
            <div className="p-3 text-[12px] text-[var(--text3)] italic">
              Result not available
            </div>
          )}
        </div>
      )}
    </div>
  )
}
