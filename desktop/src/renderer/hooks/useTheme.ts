// ── Theme Hook ──────────────────────────────────
import { useEffect } from 'react'
import { useSettingsStore, applyTheme } from '@/stores/settingsStore'

export function useTheme() {
  const theme = useSettingsStore((s) => s.theme)
  const hydrate = useSettingsStore((s) => s.hydrate)

  // Hydrate from localStorage on first mount
  useEffect(() => {
    hydrate()
  }, [])

  // Listen for system theme changes when in "system" mode
  useEffect(() => {
    if (theme !== 'system') return

    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => applyTheme('system')
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [theme])

  // Apply theme whenever it changes
  useEffect(() => {
    applyTheme(theme)
  }, [theme])
}
