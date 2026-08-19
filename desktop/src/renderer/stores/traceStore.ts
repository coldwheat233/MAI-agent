// ── Trace Store ──────────────────────────────────
// 拉取 .mai/traces 的会话列表与单会话 span 详情
import { create } from 'zustand'

export interface TraceSessionInfo {
  session_id: string
  spans: number
  llm_calls: number
  tool_calls: number
  total_tokens: number
  total_cost: number
  updated_at: number
}

export interface TraceSpan {
  ts: string
  type: 'llm' | 'tool' | 'brain' | string
  session_id: string
  turn: number
  duration_ms: number
  is_error: boolean
  model?: string
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  cost?: number
  finish_reason?: string
  tool?: string
  args?: unknown
  result?: string
  result_truncated?: boolean
  brain?: string
  extra?: Record<string, unknown>
}

export interface TraceSummary {
  llm_calls: number
  tool_calls: number
  brain_calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  total_cost: number
  total_duration_ms: number
  tool_errors: number
  tool_failures_top: Record<string, number>
  models: string[]
}

interface TraceState {
  sessions: TraceSessionInfo[]
  loading: boolean
  selectedId: string | null
  spans: TraceSpan[]
  summary: TraceSummary | null
  error: string | null

  fetchSessions: () => Promise<void>
  selectSession: (id: string | null) => Promise<void>
}

export const useTraceStore = create<TraceState>((set, get) => ({
  sessions: [],
  loading: false,
  selectedId: null,
  spans: [],
  summary: null,
  error: null,

  fetchSessions: async () => {
    try {
      const res = await fetch('/api/traces')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      set({ sessions: data, error: null })
    } catch (e) {
      set({ error: (e as Error).message })
    }
  },

  selectSession: async (id: string | null) => {
    if (!id) {
      set({ selectedId: null, spans: [], summary: null })
      return
    }
    set({ loading: true, selectedId: id })
    try {
      const res = await fetch(`/api/traces/${id}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      set({
        spans: data.spans || [],
        summary: data.summary || null,
        loading: false,
        error: null,
      })
    } catch (e) {
      set({ loading: false, error: (e as Error).message })
    }
  },
}))
