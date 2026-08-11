import { useRef, useEffect, useCallback, useState } from 'react'
import { MAX_TEXTAREA_ROWS } from '@/lib/constants'

interface InputTextareaProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  disabled?: boolean
  onKeyDown?: (e: React.KeyboardEvent) => void
}

export function InputTextarea({ value, onChange, onSubmit, disabled, onKeyDown }: InputTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [isComposing, setIsComposing] = useState(false)

  // Auto-resize
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    const baseHeight = 36
    const maxHeight = baseHeight * 3
    const newHeight = Math.min(Math.max(el.scrollHeight, baseHeight), maxHeight)
    el.style.height = `${newHeight}px`
  }, [value])

  // Focus on mount
  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    // Forward to parent handler first
    onKeyDown?.(e)
    if (e.defaultPrevented) return

    if (e.key === 'Enter' && !e.shiftKey && !isComposing) {
      e.preventDefault()
      onSubmit()
    }
  }, [onSubmit, isComposing, onKeyDown])

  return (
    <textarea
      ref={textareaRef}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={handleKeyDown}
      onCompositionStart={() => setIsComposing(true)}
      onCompositionEnd={() => setIsComposing(false)}
      placeholder="Ask anything... (Enter to send, Shift+Enter for newline)"
      disabled={disabled}
      rows={1}
      className="flex-1 bg-[var(--bg)] border border-[var(--border)] rounded-xl text-sm text-[var(--text)] px-4 py-1.5 resize-none outline-none focus:border-[var(--accent)] transition-colors placeholder:text-[var(--text3)] disabled:opacity-50 font-sans"
    />
  )
}
