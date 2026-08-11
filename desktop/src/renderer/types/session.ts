// ── Session Types ───────────────────────────────

export interface SessionInfo {
  session_id: string
  message_count: number
  updated_at?: string
  last_message?: string
}

export interface SessionDetail {
  session_id: string
  message_count: number
  messages: SessionMessage[]
}

export interface SessionMessage {
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  tool_calls?: SessionToolCall[] | null
}

export interface SessionToolCall {
  name: string
  args: string
}
