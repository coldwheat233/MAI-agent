// ── Tool Types ──────────────────────────────────

export interface ToolDefinition {
  name: string
  description: string
  safe: boolean
}

// ── Chat Message Types ──────────────────────────

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  toolCalls?: ToolCallCard[]
  isStreaming?: boolean
  isThinking?: boolean
  /** 标记这是一个"重发"产生的气泡——rerunOf 指向被重发的原 user 消息 id。
   *  纯展示/审计用：真正的对话顺序仍由后端线性追加，重发只会在末尾产生新的一轮问答。*/
  rerunOf?: string
}

export interface ToolCallCard {
  id: string
  name: string
  args: string
  result?: string
  isError?: boolean
  status: 'running' | 'ok' | 'error'
}
