import { Paperclip } from 'lucide-react'
import { useRef } from 'react'

interface AttachButtonProps {
  onFileSelect: (file: File) => void
}

export function AttachButton({ onFileSelect }: AttachButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <>
      <button
        onClick={() => inputRef.current?.click()}
        className="flex items-center justify-center w-9 h-9 rounded-lg shrink-0 text-[var(--text3)] hover:text-[var(--text2)] hover:bg-[var(--surface2)] transition-colors"
        title="Attach file"
      >
        <Paperclip size={17} />
      </button>
      <input
        ref={inputRef}
        type="file"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onFileSelect(file)
          e.target.value = ''
        }}
        className="hidden"
      />
    </>
  )
}
