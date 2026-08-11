import { useEffect, useRef } from 'react'

export interface ContextMenuItem {
  label: string
  onClick: () => void
  danger?: boolean
}

interface ContextMenuProps {
  x: number
  y: number
  items: ContextMenuItem[]
  onClose: () => void
}

export function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  useEffect(() => {
    const handler = () => onClose()
    window.addEventListener('scroll', handler, true)
    window.addEventListener('resize', handler)
    return () => {
      window.removeEventListener('scroll', handler, true)
      window.removeEventListener('resize', handler)
    }
  }, [onClose])

  return (
    <div
      ref={ref}
      className="fixed z-[100] bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-xl py-1 min-w-[140px] animate-fade-in"
      style={{ left: x, top: y }}
    >
      {items.map((item, i) => (
        <button
          key={i}
          onClick={() => { item.onClick(); onClose() }}
          className={`w-full text-left px-3 py-1.5 text-xs transition-colors ${
            item.danger
              ? 'text-[var(--red)] hover:bg-[var(--red)]/10'
              : 'text-[var(--text2)] hover:bg-[var(--surface2)] hover:text-[var(--text)]'
          }`}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
