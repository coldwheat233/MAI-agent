import type { AutocompleteItem } from '@/hooks/useAutocomplete'

interface AutocompleteProps {
  isOpen: boolean
  items: { label: string; insert: string; type: 'file' | 'memory' }[]
  selectedIndex: number
  position?: { top: number; left: number }
}

export function Autocomplete({ isOpen, items, selectedIndex, position }: AutocompleteProps) {
  if (!isOpen || items.length === 0) return null

  return (
    <div
      className="absolute z-40 bottom-full mb-2 left-0 right-0 bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-xl max-h-[180px] overflow-y-auto animate-fade-in"
    >
      {items.map((item, i) => (
        <div
          key={i}
          className={`px-3 py-2 text-xs flex items-center gap-2 cursor-pointer ${
            i === selectedIndex
              ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
              : 'text-[var(--text2)] hover:bg-[var(--surface2)]'
          }`}
        >
          <span className="text-[var(--text3)] text-[10px] font-mono uppercase w-12 shrink-0">
            {item.type}
          </span>
          <span className="truncate">{item.label}</span>
        </div>
      ))}
    </div>
  )
}

// Re-export the type used by consumers
export type { AutocompleteItem }
