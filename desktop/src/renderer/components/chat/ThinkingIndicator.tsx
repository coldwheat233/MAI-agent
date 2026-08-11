export function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-3 py-4 px-2 animate-fade-in">
      <div className="flex gap-1.5">
        <span className="w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse-dot" />
        <span className="w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse-dot" style={{ animationDelay: '0.15s' }} />
        <span className="w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse-dot" style={{ animationDelay: '0.3s' }} />
      </div>
      <span className="text-[13px] text-[var(--text3)] font-medium">Thinking...</span>
    </div>
  )
}
