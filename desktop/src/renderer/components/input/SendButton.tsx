import { Send, Square } from 'lucide-react'

interface SendButtonProps {
  isStreaming: boolean
  disabled: boolean
  onClick: () => void
}

export function SendButton({ isStreaming, disabled, onClick }: SendButtonProps) {
  if (isStreaming) {
    return (
      <button
        onClick={onClick}
        className="flex items-center justify-center w-9 h-9 rounded-xl bg-[var(--red)] hover:opacity-90 text-white transition-opacity shrink-0"
        title="Stop"
      >
        <Square size={16} fill="currentColor" />
      </button>
    )
  }

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex items-center justify-center w-9 h-9 rounded-xl bg-[var(--accent)] hover:opacity-90 text-white transition-opacity disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
      title="Send"
    >
      <Send size={16} />
    </button>
  )
}
