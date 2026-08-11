// ── Keyboard Hook ───────────────────────────────
import { useEffect } from 'react'

interface KeyboardHandlers {
  onEscape?: () => void
  onSlash?: () => void
  onNewSession?: () => void
}

export function useKeyboard(handlers: KeyboardHandlers) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't capture when typing in input/textarea
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') {
        // Allow Escape even in inputs
        if (e.key === 'Escape') {
          handlers.onEscape?.()
        }
        return
      }

      switch (e.key) {
        case 'Escape':
          handlers.onEscape?.()
          break
        case '/':
          handlers.onSlash?.()
          break
        case 'n':
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault()
            handlers.onNewSession?.()
          }
          break
      }
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [handlers])
}
