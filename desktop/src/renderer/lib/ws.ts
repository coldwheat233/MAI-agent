// ── WebSocket Message Handler ────────────────────
import type { ServerEvent, OutgoingMessage } from '@/types'

// Re-export for convenience
export type { ServerEvent, OutgoingMessage }

/**
 * Central message dispatcher.
 * Called by wsStore on each incoming message.
 * Routes events to the appropriate Zustand stores.
 */
export function createWSHandler(stores: {
  chatStore: any
  sessionStore: any
  settingsStore: any
  toolStore: any
  workspaceStore: any
}) {
  return function handleWSMessage(event: ServerEvent) {
    const { chatStore, sessionStore, settingsStore, toolStore } = stores

    switch (event.type) {
      case 'ready': {
        if (event.model) settingsStore.setModelFromServer(event.model)
        if (event.tools) toolStore.setTools(event.tools)
        // 同步后端引擎的 session_id — 之前前端 currentSessionId 永远停在 'default'，
        // 导致新引擎的 session 无法在侧边栏高亮/标记为"当前会话"。
        if (event.session_id) sessionStore.setCurrentSessionId(event.session_id)
        break
      }
      case 'thinking': {
        chatStore.startThinking()
        break
      }
      case 'text': {
        chatStore.appendText(event.data)
        break
      }
      case 'tool_start': {
        chatStore.startTool(event.tool, event.args)
        break
      }
      case 'tool_result': {
        chatStore.finishTool(event.tool, event.result, event.error)
        break
      }
      case 'converge': {
        chatStore.converge(event.answer, event.tokens, event.context_tokens)
        break
      }
      case 'done': {
        chatStore.completeStream(event.turn, event.tools_called)
        sessionStore.fetchSessions()
        break
      }
      case 'error': {
        chatStore.handleError(event.message)
        break
      }
      case 'workspace_switched': {
        if (event.cwd) {
          const ws = stores.workspaceStore
          ws.setCwd(event.cwd)
          if (event.session_id) sessionStore.setCurrentSessionId(event.session_id)
          stores.sessionStore.fetchSessions()
        }
        break
      }
      case 'undo': {
        chatStore.trimToLastUserMessage()
        break
      }
      case 'status': {
        console.log('[ws:status]', event.message)
        break
      }
    }
  }
}
