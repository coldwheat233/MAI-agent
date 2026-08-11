// ── Chat Store ──────────────────────────────────
import { create } from 'zustand'
import type { ChatMessage, ToolCallCard } from '@/types'

let nextId = 1
function genId(): string {
  return `msg_${Date.now()}_${nextId++}`
}

function genToolId(): string {
  return `tool_${Date.now()}_${nextId++}`
}

interface ChatState {
  messages: ChatMessage[]
  isStreaming: boolean
  streamingMsgId: string | null
  tokensUsed: number
  contextTokens: number
  turnCount: number
  toolCallCount: number

  // Actions
  addUserMessage: (text: string, opts?: { rerunOf?: string }) => string
  updateUserMessage: (id: string, newText: string) => void
  startThinking: () => void
  appendText: (delta: string) => void
  startTool: (name: string, args: string) => void
  finishTool: (name: string, result: string, isError: boolean) => void
  converge: (answer: string, tokens: number, ctxTokens: number) => void
  completeStream: (turn: number, toolsCalled: number) => void
  handleError: (message: string) => void
  clearMessages: () => void
  setMessages: (msgs: ChatMessage[]) => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,
  streamingMsgId: null,
  tokensUsed: 0,
  contextTokens: 0,
  turnCount: 0,
  toolCallCount: 0,

  addUserMessage: (text, opts) => {
    const id = genId()
    const msg: ChatMessage = {
      id,
      role: 'user',
      content: text,
      timestamp: Date.now(),
      ...(opts?.rerunOf ? { rerunOf: opts.rerunOf } : {}),
    }
    // 严格 append：生成全新 id，绝不替换任何已有消息的 id / content。
    // 对既有 assistant 只清 isStreaming/isThinking 标志（不触碰 content），
    // 避免"上一轮还在打字"和新一轮的流式光标打架。
    set((s) => ({
      messages: [
        ...s.messages.map((m) =>
          m.role === 'assistant' ? { ...m, isStreaming: false, isThinking: false } : m
        ),
        msg,
      ],
      isStreaming: false,
      streamingMsgId: null,
    }))
    return id
  },

  updateUserMessage: (id, newText) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, content: newText, timestamp: Date.now() } : m
      ),
    }))
  },

  startThinking: () => {
    const id = genId()
    const msg: ChatMessage = {
      id,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isStreaming: true,
      isThinking: true,
      toolCalls: [],
    }
    set((s) => ({
      messages: [...s.messages, msg],
      isStreaming: true,
      streamingMsgId: id,
    }))
  },

  appendText: (delta) => {
    const { streamingMsgId } = get()
    if (!streamingMsgId) return
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === streamingMsgId
          ? { ...m, content: m.content + delta, isThinking: false }
          : m
      ),
    }))
  },

  startTool: (name, args) => {
    const { streamingMsgId } = get()
    const toolCard: ToolCallCard = {
      id: genToolId(),
      name,
      args,
      status: 'running',
    }
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === streamingMsgId
          ? { ...m, toolCalls: [...(m.toolCalls || []), toolCard], isThinking: false }
          : m
      ),
    }))
  },

  finishTool: (name, result, isError) => {
    const { streamingMsgId } = get()
    set((s) => ({
      messages: s.messages.map((m) => {
        if (m.id !== streamingMsgId || !m.toolCalls) return m
        return {
          ...m,
          toolCalls: m.toolCalls.map((tc) => {
            // Update the first matching running tool
            if (tc.name === name && tc.status === 'running') {
              return { ...tc, result, isError, status: isError ? 'error' : 'ok' }
            }
            return tc
          }),
        }
      }),
    }))
  },

  converge: (answer, tokens, ctxTokens) => {
    set({ tokensUsed: tokens, contextTokens: ctxTokens })
  },

  completeStream: (turn, toolsCalled) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === s.streamingMsgId ? { ...m, isStreaming: false, isThinking: false } : m
      ),
      isStreaming: false,
      streamingMsgId: null,
      turnCount: turn,
      toolCallCount: toolsCalled,
    }))
  },

  handleError: (message) => {
    const { streamingMsgId } = get()
    if (streamingMsgId) {
      set((s) => ({
        messages: s.messages.map((m) =>
          m.id === streamingMsgId
            ? { ...m, content: m.content + `\n\n> ⚠️ ${message}`, isStreaming: false, isThinking: false }
            : m
        ),
        isStreaming: false,
        streamingMsgId: null,
      }))
    }
  },

  clearMessages: () =>
    set({ messages: [], isStreaming: false, streamingMsgId: null }),
  setMessages: (msgs) => set({ messages: msgs }),
}))
