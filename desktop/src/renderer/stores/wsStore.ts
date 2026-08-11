// ── WebSocket Store ─────────────────────────────
import { create } from 'zustand'
import type { ServerEvent, OutgoingMessage } from '@/types'
import { RECONNECT_BASE_MS, RECONNECT_MAX_MS } from '@/lib/constants'

interface WSState {
  socket: WebSocket | null
  status: 'connecting' | 'connected' | 'disconnected'
  reconnectAttempts: number
  serverUrl: string

  connect: (messageHandler: (event: ServerEvent) => void) => void
  disconnect: () => void
  send: (msg: OutgoingMessage) => void
}

export const useWSStore = create<WSState>((set, get) => ({
  socket: null,
  status: 'disconnected',
  reconnectAttempts: 0,
  serverUrl: '',

  connect: (messageHandler) => {
    const { socket, status } = get()
    if (socket && (status === 'connected' || status === 'connecting')) {
      return // Already connected or connecting
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws`

    set({ status: 'connecting', serverUrl: url })

    const ws = new WebSocket(url)

    ws.onopen = () => {
      set({ status: 'connected', reconnectAttempts: 0 })
    }

    ws.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as ServerEvent
        messageHandler(event)
      } catch (err) {
        console.error('[ws] Failed to parse message:', err)
      }
    }

    ws.onclose = () => {
      set({ status: 'disconnected' })
      // Reconnect with exponential backoff
      const attempts = get().reconnectAttempts
      const delay = Math.min(RECONNECT_BASE_MS * Math.pow(2, attempts), RECONNECT_MAX_MS)
      set({ reconnectAttempts: attempts + 1 })
      setTimeout(() => {
        if (get().status === 'disconnected') {
          get().connect(messageHandler)
        }
      }, delay)
    }

    ws.onerror = () => {
      // onclose will fire after this, triggering reconnect
    }

    set({ socket: ws })
  },

  disconnect: () => {
    const { socket } = get()
    if (socket) {
      socket.close()
      set({ socket: null, status: 'disconnected' })
    }
  },

  send: (msg) => {
    const { socket, status } = get()
    if (socket && status === 'connected') {
      socket.send(JSON.stringify(msg))
    }
  },
}))
