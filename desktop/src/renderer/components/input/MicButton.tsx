import { Mic, MicOff } from 'lucide-react'
import { useState } from 'react'

export function MicButton() {
  const [active, setActive] = useState(false)

  const handleToggle = () => {
    if (!('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
      return
    }
    setActive(!active)
  }

  return (
    <button
      onClick={handleToggle}
      className={`flex items-center justify-center w-9 h-9 rounded-lg shrink-0 transition-colors ${
        active
          ? 'text-[var(--accent)] bg-[var(--accent)]/10'
          : 'text-[var(--text3)] hover:text-[var(--text2)] hover:bg-[var(--surface2)]'
      }`}
      title="Voice input"
    >
      {active ? <Mic size={17} /> : <MicOff size={17} />}
    </button>
  )
}
