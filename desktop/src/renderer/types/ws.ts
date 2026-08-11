// ── WebSocket Message Types ──────────────────────

export type ServerEvent =
  | ReadyEvent
  | ThinkingEvent
  | TextEvent
  | ToolStartEvent
  | ToolResultEvent
  | ConvergeEvent
  | DoneEvent
  | ErrorEvent
  | StatusEvent
  | WorkspaceSwitchedEvent

export interface ReadyEvent {
  type: 'ready'
  session_id: string
  mode: string
  brain: string
  sandbox: string
  model: string
  tools: string[]
}

export interface ThinkingEvent {
  type: 'thinking'
}

export interface TextEvent {
  type: 'text'
  data: string
}

export interface ToolStartEvent {
  type: 'tool_start'
  tool: string
  args: string
}

export interface ToolResultEvent {
  type: 'tool_result'
  tool: string
  result: string
  error: boolean
}

export interface ConvergeEvent {
  type: 'converge'
  answer: string
  tokens: number
  context_tokens: number
  max_context: number
}

export interface DoneEvent {
  type: 'done'
  turn: number
  tools_called: number
  pending_tasks: number
}

export interface ErrorEvent {
  type: 'error'
  message: string
}

export interface StatusEvent {
  type: 'status'
  message: string
}

export interface WorkspaceSwitchedEvent {
  type: 'workspace_switched'
  cwd: string
  session_id: string
  mode: string
}

// ── Outgoing Messages ───────────────────────────

export type OutgoingMessage =
  | SubmitMessage
  | StopMessage
  | UndoMessage
  | SwitchWorkspaceMessage

export interface SubmitMessage {
  type: 'submit'
  text: string
  mode?: string
  brain?: string
}

export interface StopMessage {
  type: 'stop'
}

export interface UndoMessage {
  type: 'undo'
}

export interface SwitchWorkspaceMessage {
  type: 'switch_workspace'
  cwd: string
}
