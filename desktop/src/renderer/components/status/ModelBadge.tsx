import { Cpu } from 'lucide-react'
import { useSettingsStore } from '@/stores/settingsStore'

export function ModelBadge() {
  const model = useSettingsStore((s) => s.model)

  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-[var(--accent)]/10 text-[var(--accent)]">
      <Cpu size={10} />
      {model}
    </span>
  )
}
