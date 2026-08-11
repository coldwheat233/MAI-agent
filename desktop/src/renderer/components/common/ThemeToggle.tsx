import { Sun, Moon, Monitor } from 'lucide-react'
import { useSettingsStore } from '@/stores/settingsStore'
import type { Theme } from '@/types'

const themes: { id: Theme; icon: typeof Sun; label: string }[] = [
  { id: 'light', icon: Sun, label: 'Light' },
  { id: 'dark', icon: Moon, label: 'Dark' },
  { id: 'system', icon: Monitor, label: 'System' },
]

export function ThemeToggle() {
  const current = useSettingsStore((s) => s.theme)
  const setTheme = useSettingsStore((s) => s.setTheme)

  const cycle = () => {
    const idx = themes.findIndex((t) => t.id === current)
    const next = themes[(idx + 1) % themes.length]
    setTheme(next.id)
  }

  const Icon = themes.find((t) => t.id === current)?.icon || Moon

  return (
    <button
      onClick={cycle}
      className="p-1.5 rounded-md hover:bg-[var(--surface2)] text-[var(--text2)] hover:text-[var(--text)] transition-colors"
      title={`Theme: ${current}`}
    >
      <Icon size={16} />
    </button>
  )
}
