import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft, Bot, Wrench, AlertTriangle, Clock, Coins, Layers, ChevronDown, ChevronRight,
  Cpu, Play,
} from 'lucide-react'
import { useTraceStore } from '@/stores/traceStore'
import { useWSStore } from '@/stores/wsStore'
import type { TraceSpan } from '@/stores/traceStore'

function fmtCost(cost: number): string {
  if (cost <= 0) return '$0'
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  return `$${cost.toFixed(3)}`
}

function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return `${n}`
}

function fmtTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}

function fmtDur(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtAge(ts: number): string {
  const diff = Date.now() - ts * 1000
  if (diff < 60_000) return '刚刚'
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}h ago`
  return `${Math.floor(diff / 86400_000)}d ago`
}

function spanKind(span: TraceSpan): 'llm' | 'tool' | 'brain' | 'other' {
  if (span.type === 'llm') return 'llm'
  if (span.type === 'tool') return 'tool'
  if (span.type === 'brain') return 'brain'
  return 'other'
}

function spanColor(kind: string, isError: boolean): string {
  if (isError) return 'text-red-500'
  if (kind === 'llm') return 'text-[var(--accent)]'
  if (kind === 'tool') return 'text-emerald-500'
  if (kind === 'brain') return 'text-purple-500'
  return 'text-[var(--text3)]'
}

function spanIcon(kind: string): React.ReactNode {
  if (kind === 'llm') return <Cpu size={12} />
  if (kind === 'tool') return <Wrench size={12} />
  if (kind === 'brain') return <Layers size={12} />
  return <Play size={12} />
}

/** 单条 span 的展开 inspector：token / 耗时 / Input / Output / Timing（对齐 DSH 的 local inspector） */
function SpanInspector({ span, index }: { span: TraceSpan; index: number }) {
  const [open, setOpen] = useState(false)
  const kind = spanKind(span)
  const isLlm = kind === 'llm'
  const isTool = kind === 'tool'
  const title = isLlm ? (span.model || 'LLM') : isTool ? (span.tool || 'tool') : (span.brain || span.type)

  return (
    <div className="relative">
      {/* 展开后的内容 */}
      {open && (
        <div className="ml-[21px] px-3 pb-3 pt-1 space-y-2 text-[11px]">
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[var(--text2)] border-b border-[var(--border)] pb-1.5">
            <span>#{index}</span>
            <span>{fmtTime(span.ts)}</span>
            <span>dur {fmtDur(span.duration_ms)}</span>
            {isLlm && (
              <>
                <span>in {fmtTokens(span.input_tokens ?? 0)}</span>
                <span>out {fmtTokens(span.output_tokens ?? 0)}</span>
                <span>finish {span.finish_reason || '—'}</span>
                <span>{fmtCost(span.cost ?? 0)}</span>
                {span.extra?.usage_estimated && <span className="text-[var(--text3)]">(估算)</span>}
              </>
            )}
          </div>
          {isTool && span.args !== undefined && (
            <div>
              <div className="text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide mb-1">Input</div>
              <pre className="bg-[var(--bg)] rounded p-2 overflow-x-auto text-[10px] leading-relaxed text-[var(--text2)] max-h-40 overflow-y-auto">
                {JSON.stringify(span.args, null, 2)}
              </pre>
            </div>
          )}
          {isTool && span.result !== undefined && (
            <div>
              <div className="text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide mb-1">Output</div>
              <pre className={`bg-[var(--bg)] rounded p-2 overflow-x-auto text-[10px] leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap ${span.is_error ? 'text-red-400' : 'text-[var(--text2)]'}`}>
                {span.result}
                {span.result_truncated && '\n…(truncated)'}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* 行主体：紧凑一行（index · event · content） */}
      <button
        onClick={() => setOpen(!open)}
        className={`w-full flex items-center gap-2 py-1.5 pr-2 text-left rounded hover:bg-[var(--surface2)] transition-colors ${
          open ? 'bg-[var(--surface2)]/60' : ''
        }`}
      >
        {open ? <ChevronDown size={12} className="text-[var(--text3)] shrink-0 ml-[2px]" /> : <ChevronRight size={12} className="text-[var(--text3)] shrink-0 ml-[2px]" />}
        <span className={`shrink-0 ${spanColor(kind, span.is_error)}`}>{spanIcon(kind)}</span>
        <span className="text-[10px] text-[var(--text3)] font-mono shrink-0 w-6 text-right">{index}</span>
        <span className={`text-xs font-medium truncate flex-1 ${spanColor(kind, span.is_error)}`}>{title}</span>
        {span.is_error && <AlertTriangle size={12} className="text-red-500 shrink-0" />}
        <span className="text-[10px] text-[var(--text3)] shrink-0 tabular-nums">{fmtDur(span.duration_ms)}</span>
        {isLlm && span.total_tokens !== undefined && (
          <span className="text-[10px] text-[var(--text3)] shrink-0 tabular-nums">{fmtTokens(span.total_tokens)} tok</span>
        )}
        {isLlm && span.cost !== undefined && (
          <span className="text-[10px] text-[var(--text3)] shrink-0 tabular-nums">{fmtCost(span.cost)}</span>
        )}
      </button>
    </div>
  )
}

/** 顶部 Overview：把每个 span 的 start/duration 从左到右投影成时间轴条（对齐 DSH fixed Overview） */
function TraceOverview({ spans }: { spans: TraceSpan[] }) {
  const bars = useMemo(() => {
    const parsed = spans.map((s) => ({
      span: s,
      start: new Date(s.ts).getTime(),
      dur: Math.max(s.duration_ms || 0, 1),
    }))
    if (parsed.length === 0) return []
    const min = Math.min(...parsed.map((p) => p.start))
    const max = Math.max(...parsed.map((p) => p.start + p.dur))
    const range = Math.max(max - min, 1)
    return parsed.map((p) => ({
      kind: spanKind(p.span),
      isError: p.span.is_error,
      left: ((p.start - min) / range) * 100,
      width: Math.max((p.dur / range) * 100, 1.2),
    }))
  }, [spans])

  if (bars.length === 0) return null

  const barColor = (kind: string, isError: boolean): string => {
    if (isError) return 'bg-red-500'
    if (kind === 'llm') return 'bg-[var(--accent)]'
    if (kind === 'tool') return 'bg-emerald-500'
    if (kind === 'brain') return 'bg-purple-500'
    return 'bg-[var(--text3)]'
  }

  return (
    <div className="px-4 py-2 border-b border-[var(--border)]">
      <div className="text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide mb-1 flex items-center gap-1">
        <Clock size={10} /> Timeline
      </div>
      <div className="relative h-4 rounded bg-[var(--bg)] overflow-hidden">
        {bars.map((b, i) => (
          <div
            key={i}
            className={`absolute top-0 bottom-0 rounded-sm opacity-80 ${barColor(b.kind, b.isError)}`}
            style={{ left: `${b.left}%`, width: `${b.width}%` }}
            title={`${b.kind}${b.isError ? ' (error)' : ''} @ ${b.left.toFixed(1)}%`}
          />
        ))}
      </div>
      <div className="flex items-center gap-3 mt-1 text-[9px] text-[var(--text3)]">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-[var(--accent)] inline-block" /> LLM</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-emerald-500 inline-block" /> Tool</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-purple-500 inline-block" /> Brain</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-red-500 inline-block" /> Error</span>
      </div>
    </div>
  )
}

export function TracesPanel() {
  const {
    sessions, loading, selectedId, spans, summary, error,
    fetchSessions, selectSession,
  } = useTraceStore()
  // WS 实时驱动：每条 WS 消息 tick +1，debounce 后自动刷新当前会话的 trace
  const eventTick = useWSStore((s) => s.eventTick)
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    fetchSessions()
  }, [])

  // 会话进行中：WS 事件到达 → debounce 500ms 刷新列表 + 当前 trace
  useEffect(() => {
    if (eventTick === 0) return
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
    refreshTimer.current = setTimeout(() => {
      fetchSessions()
      if (selectedId) selectSession(selectedId)
    }, 500)
    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current)
    }
  }, [eventTick])

  // 线性 ledger：所有 span 按时间顺序串成一串，Turn 变化处插入边界
  // （对齐 DSH ui-trajectory 的 turn-aware event ledger）
  const ledger = useMemo(() => {
    const rows: Array<{ kind: 'turn' | 'span'; turn?: number; span?: TraceSpan; index?: number }> = []
    let lastTurn: number | null = null
    let idx = 0
    for (const s of spans) {
      const t = s.turn ?? 0
      if (lastTurn === null || t !== lastTurn) {
        rows.push({ kind: 'turn', turn: t })
        lastTurn = t
      }
      rows.push({ kind: 'span', span: s, index: idx })
      idx++
    }
    return rows
  }, [spans])

  // 详情视图
  if (selectedId) {
    return (
      <div className="flex flex-col h-full">
        <div className="px-4 py-3 border-b border-[var(--border)]">
          <button
            onClick={() => selectSession(null)}
            className="flex items-center gap-1 text-xs text-[var(--accent)] hover:underline mb-2"
          >
            <ArrowLeft size={13} /> Back to sessions
          </button>
          <h4 className="text-sm font-bold text-[var(--text)] font-mono truncate">{selectedId}</h4>
          {/* 聚合条 */}
          {summary && (
            <div className="mt-2 grid grid-cols-2 gap-1.5">
              <div className="flex items-center gap-1.5 text-[10px] text-[var(--text2)]">
                <Bot size={12} className="text-[var(--accent)]" /> {summary.llm_calls} LLM
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-[var(--text2)]">
                <Wrench size={12} className="text-emerald-500" /> {summary.tool_calls} tools
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-[var(--text2)]">
                <Coins size={12} className="text-amber-500" /> {fmtCost(summary.total_cost)}
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-[var(--text2)]">
                <Clock size={12} className="text-sky-500" /> {fmtDur(summary.total_duration_ms)}
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-[var(--text2)]">
                <Layers size={12} className="text-purple-500" /> {fmtTokens(summary.total_tokens)} tok
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-[var(--text2)]">
                <AlertTriangle size={12} className="text-red-500" /> {summary.tool_errors} errors
              </div>
            </div>
          )}
        </div>

        {/* Overview 时间轴投影 */}
        {!loading && spans.length > 0 && <TraceOverview spans={spans} />}

        {/* 串联 ledger：一条时间线串到底 */}
        <div className="flex-1 overflow-y-auto py-2 px-2">
          {loading && <div className="text-xs text-[var(--text3)] text-center py-8">Loading trace...</div>}
          {!loading && spans.length === 0 && (
            <div className="text-xs text-[var(--text3)] text-center py-8">No spans in this trace.</div>
          )}
          {ledger.map((row, i) => {
            if (row.kind === 'turn') {
              return (
                <div key={`turn-${row.turn}-${i}`} className="flex items-center gap-2 my-1.5 first:mt-0">
                  <span className="text-[10px] font-bold text-[var(--text3)] uppercase tracking-widest shrink-0">
                    Turn {row.turn}
                  </span>
                  <div className="flex-1 h-px bg-[var(--border)]" />
                  <span className="text-[9px] text-[var(--text3)]">—</span>
                </div>
              )
            }
            return (
              <SpanInspector key={`span-${row.span!.ts}-${i}`} span={row.span!} index={row.index ?? 0} />
            )
          })}
          {summary && summary.tool_failures_top && Object.keys(summary.tool_failures_top).length > 0 && (
            <div className="pt-2 mt-2 border-t border-[var(--border)]">
              <div className="text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide mb-1.5">Tool failures</div>
              {Object.entries(summary.tool_failures_top).map(([name, count]) => (
                <div key={name} className="flex items-center justify-between text-[11px] py-0.5">
                  <span className="text-[var(--text2)] font-mono">{name}</span>
                  <span className="text-red-500 font-medium">{count}×</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  // 会话列表视图
  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
        <h4 className="text-sm font-semibold text-[var(--text)]">Traces</h4>
        <button
          onClick={fetchSessions}
          className="text-[10px] text-[var(--accent)] hover:underline"
        >
          Refresh
        </button>
      </div>
      {error && <div className="px-4 py-2 text-[11px] text-red-500">{error}</div>}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sessions.length === 0 && (
          <div className="text-[11px] text-[var(--text3)] text-center py-8">
            暂无轨迹。<br />运行一次对话后这里会显示 span 级记录。
          </div>
        )}
        {sessions.map((s) => (
          <button
            key={s.session_id}
            onClick={() => selectSession(s.session_id)}
            className="w-full text-left px-3 py-2 rounded-md hover:bg-[var(--surface2)] transition-colors"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-mono text-[var(--text)] truncate">{s.session_id}</span>
              <span className="text-[10px] text-[var(--text3)] shrink-0">{fmtAge(s.updated_at)}</span>
            </div>
            <div className="flex items-center gap-2 mt-1 text-[10px] text-[var(--text3)]">
              <span>{s.llm_calls} LLM</span>
              <span>·</span>
              <span>{s.tool_calls} tools</span>
              <span>·</span>
              <span>{fmtTokens(s.total_tokens)} tok</span>
              <span>·</span>
              <span>{fmtCost(s.total_cost)}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
