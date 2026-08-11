// ── Command Menu Hook ───────────────────────────
import { useState, useCallback } from 'react'
import { useUIStore } from '@/stores/uiStore'
import { useSessionStore } from '@/stores/sessionStore'
import { useChatStore } from '@/stores/chatStore'
import { useWSStore } from '@/stores/wsStore'

export interface Command {
  id: string
  label: string
  description: string
  action: () => void
}

export function useCommandMenu() {
  const [isOpen, setIsOpen] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(0)

  const openSettings = useUIStore((s) => s.openSettings)
  const openPanel = useUIStore((s) => s.openPanel)
  const newSession = useSessionStore((s) => s.newSession)
  const clearMessages = useChatStore((s) => s.clearMessages)
  const send = useWSStore((s) => s.send)

  const commands: Command[] = [
    { id: 'new', label: '/new', description: '新建会话', action: () => { newSession(); clearMessages(); } },
    { id: 'clear', label: '/clear', description: '清空当前对话', action: () => clearMessages() },
    { id: 'settings', label: '/settings', description: '打开设置', action: () => openSettings() },
    { id: 'memory', label: '/memory', description: '查看记忆卡片', action: () => openPanel('memory') },
    { id: 'skills', label: '/skills', description: '查看技能列表', action: () => openPanel('skills') },
    { id: 'git', label: '/git', description: 'Git 状态', action: () => openPanel('git') },
    { id: 'undo', label: '/undo', description: '撤销最近一轮对话', action: () => send({ type: 'undo' }) },
  ]

  const open = useCallback(() => {
    setIsOpen(true)
    setSelectedIndex(0)
  }, [])

  const close = useCallback(() => {
    setIsOpen(false)
  }, [])

  const moveDown = useCallback(() => {
    setSelectedIndex((i) => Math.min(i + 1, commands.length - 1))
  }, [commands.length])

  const moveUp = useCallback(() => {
    setSelectedIndex((i) => Math.max(i - 1, 0))
  }, [])

  const execute = useCallback(() => {
    const cmd = commands[selectedIndex]
    if (cmd) {
      cmd.action()
      setIsOpen(false)
    }
  }, [commands, selectedIndex])

  return { isOpen, commands, selectedIndex, open, close, moveDown, moveUp, execute }
}
