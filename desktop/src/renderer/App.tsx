import { useEffect, useCallback } from 'react'
import { Sidebar } from '@/components/sidebar/Sidebar'
import { ChatArea } from '@/components/chat/ChatArea'
import { InputArea } from '@/components/input/InputArea'
import { StatusBar } from '@/components/status/StatusBar'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { PanelContainer } from '@/components/panels/PanelContainer'
import { SettingsModal } from '@/components/settings/SettingsModal'
import { useTheme } from '@/hooks/useTheme'
import { useKeyboard } from '@/hooks/useKeyboard'
import { useWSStore } from '@/stores/wsStore'
import { useChatStore } from '@/stores/chatStore'
import { useSessionStore } from '@/stores/sessionStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useToolStore } from '@/stores/toolStore'
import { useGitStore } from '@/stores/gitStore'
import { useSettingsStore } from '@/stores/settingsStore'
import { useUIStore } from '@/stores/uiStore'
import { createWSHandler } from '@/lib/ws'

export default function App() {
  // Theme
  useTheme()

  // Stores
  const connect = useWSStore((s) => s.connect)
  const send = useWSStore((s) => s.send)
  const addUserMessage = useChatStore((s) => s.addUserMessage)
  const fetchSessions = useSessionStore((s) => s.fetchSessions)
  const fetchWorkspace = useWorkspaceStore((s) => s.fetchWorkspace)
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces)
  const fetchTools = useToolStore((s) => s.fetchTools)
  const fetchGitStatus = useGitStore((s) => s.fetchGitStatus)
  const fetchFeishuStatus = useSettingsStore((s) => s.fetchFeishuStatus)
  const permission = useSettingsStore((s) => s.permission)
  const closePanel = useUIStore((s) => s.closePanel)
  const openSettings = useUIStore((s) => s.openSettings)
  const newSession = useSessionStore((s) => s.newSession)

  // Initial data fetch
  const loadInitialData = useCallback(async () => {
    fetchWorkspace()
    fetchWorkspaces()
    fetchSessions()
    fetchTools()
    fetchGitStatus()
    fetchFeishuStatus()
  }, [])

  // Connect WebSocket on mount
  useEffect(() => {
    // Create message handler that routes to stores
    const handler = createWSHandler({
      chatStore: useChatStore.getState(),
      sessionStore: useSessionStore.getState(),
      settingsStore: useSettingsStore.getState(),
      toolStore: useToolStore.getState(),
      workspaceStore: useWorkspaceStore.getState(),
    })

    // Create a stable handler reference
    const wrappedHandler = (event: any) => {
      // Re-read stores on each message to get latest state
      const h = createWSHandler({
        chatStore: useChatStore.getState(),
        sessionStore: useSessionStore.getState(),
        settingsStore: useSettingsStore.getState(),
        toolStore: useToolStore.getState(),
        workspaceStore: useWorkspaceStore.getState(),
      })
      h(event)
    }

    connect(wrappedHandler)

    // Load initial data after WS connects
    const timer = setTimeout(loadInitialData, 500)
    return () => clearTimeout(timer)
  }, [])

  // Refresh git status periodically
  useEffect(() => {
    const interval = setInterval(fetchGitStatus, 30000)
    return () => clearInterval(interval)
  }, [])

  // Keyboard shortcuts
  useKeyboard({
    onEscape: () => closePanel(),
    onNewSession: () => { newSession(); useChatStore.getState().clearMessages() },
  })

  // Message submission
  const handleSubmit = useCallback((text: string) => {
    addUserMessage(text)
    send({ type: 'submit', text, mode: permission })
  }, [addUserMessage, send, permission])

  const handleResubmit = useCallback((text: string, afterMsgId: string) => {
    // 追加式重发：原问答对完整保留（绝不动最末尾那条消息），只在 chat 末尾
    // 新增一轮 user + assistant。addUserMessage 用新 id 严格 append，并通过
    // rerunOf 把"这条是重发的"标记带上，方便 UI 区分"重复提问"和"新提问"。
    // 后端 engine.submit 同样把新 user 消息 append 到 engine._messages 末尾，
    // 完整消息历史整体存盘——所以最近一条消息永远不会被覆盖。
    if (!text.trim()) return
    addUserMessage(text, { rerunOf: afterMsgId })
    send({ type: 'submit', text, mode: permission })
  }, [addUserMessage, send, permission])

  return (
    <div className="h-full flex bg-[var(--bg)] text-[var(--text)]">
      {/* Sidebar */}
      <Sidebar />

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-10 px-4 bg-[var(--surface)] border-b border-[var(--border)] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-[var(--text)] tracking-tight">
              MAI-agent
            </span>
            <span className="text-[10px] text-[var(--text3)]">v0.3</span>
          </div>
          <ThemeToggle />
        </header>

        {/* Chat area */}
        <ChatArea onPromptSubmit={handleSubmit} onResubmit={handleResubmit} />

        {/* Input area */}
        <InputArea onSubmit={handleSubmit} />

        {/* Status bar */}
        <StatusBar />
      </div>

      {/* Slide-out panels */}
      <PanelContainer />

      {/* Settings modal */}
      <SettingsModal />
    </div>
  )
}
