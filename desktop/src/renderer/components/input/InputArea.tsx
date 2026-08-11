import { useState, useRef, useCallback } from 'react'
import { InputTextarea } from './InputTextarea'
import { Autocomplete } from './Autocomplete'
import { CommandMenu } from './CommandMenu'
import { SendButton } from './SendButton'
import { MicButton } from './MicButton'
import { AttachButton } from './AttachButton'
import { ImagePasteHandler } from './ImagePasteHandler'
import { useAutocomplete } from '@/hooks/useAutocomplete'
import { useCommandMenu } from '@/hooks/useCommandMenu'
import { useChatStore } from '@/stores/chatStore'
import { useSettingsStore } from '@/stores/settingsStore'
import { useWSStore } from '@/stores/wsStore'
import { Shield, Cpu } from 'lucide-react'
import { MODELS, PERMISSION_OPTIONS } from '@/lib/constants'
import type { Permission } from '@/types'

interface InputAreaProps {
  onSubmit: (text: string) => void
}

export function InputArea({ onSubmit }: InputAreaProps) {
  const [value, setValue] = useState('')
  const [pastedFiles, setPastedFiles] = useState<File[]>([])
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const model = useSettingsStore((s) => s.model)
  const permission = useSettingsStore((s) => s.permission)
  const setModel = useSettingsStore((s) => s.setModel)
  const setPermission = useSettingsStore((s) => s.setPermission)
  const send = useWSStore((s) => s.send)

  const cycleModel = () => {
    const idx = MODELS.indexOf(model)
    const next = MODELS[(idx + 1) % MODELS.length]
    setModel(next)
  }

  const cyclePermission = () => {
    const opts = PERMISSION_OPTIONS.map((o) => o.value)
    const idx = opts.indexOf(permission)
    const next = opts[(idx + 1) % opts.length] as Permission
    setPermission(next)
  }

  const autocomplete = useAutocomplete()
  const commandMenu = useCommandMenu()

  const handleChange = useCallback((newValue: string) => {
    setValue(newValue)

    // Check for / command
    if (newValue === '/') {
      commandMenu.open()
    }

    // Check for @ autocomplete
    const cursorPos = textareaRef.current?.selectionStart || newValue.length
    autocomplete.detect(newValue, cursorPos)
  }, [autocomplete, commandMenu])

  const handleSubmit = useCallback(() => {
    // Always read stream state directly from store to avoid stale closure
    const streaming = useChatStore.getState().isStreaming
    if (streaming) {
      send({ type: 'stop' })
      return
    }
    const trimmed = value.trim()
    if (!trimmed) return

    // Build text with pasted files context
    let text = trimmed
    if (pastedFiles.length > 0) {
      text += '\n\n[Attached files: ' + pastedFiles.map((f) => f.name).join(', ') + ']'
      setPastedFiles([])
    }

    setValue('')
    onSubmit(text)
    autocomplete.close()
    commandMenu.close()
  }, [value, pastedFiles, send, onSubmit, autocomplete, commandMenu])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (autocomplete.isOpen) {
      if (e.key === 'ArrowDown') { e.preventDefault(); autocomplete.moveDown(); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); autocomplete.moveUp(); return }
      if (e.key === 'Tab' || e.key === 'Enter') {
        e.preventDefault()
        const result = autocomplete.select()
        if (result) {
          const newValue = value.slice(0, result.start) + result.replacement + value.slice(result.end)
          setValue(newValue)
        }
        return
      }
      if (e.key === 'Escape') { autocomplete.close(); return }
    }

    if (commandMenu.isOpen) {
      if (e.key === 'ArrowDown') { e.preventDefault(); commandMenu.moveDown(); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); commandMenu.moveUp(); return }
      if (e.key === 'Enter') { e.preventDefault(); commandMenu.execute(); setValue(''); return }
      if (e.key === 'Escape') { commandMenu.close(); return }
    }
  }, [autocomplete, commandMenu, value])

  const handleFileSelect = useCallback((file: File) => {
    setPastedFiles((prev) => [...prev, file])
    // Append file reference to text
    setValue((prev) => prev + `\n@${file.name}`)
  }, [])

  const handleImagePaste = useCallback((file: File) => {
    setPastedFiles((prev) => [...prev, file])
    setValue((prev) => prev + `\n[pasted image: ${file.name}]`)
  }, [])

  return (
    <div className="border-t border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="max-w-3xl mx-auto relative">
        {/* Model & Permission toggles */}
        <div className="flex items-center gap-2 mb-2">
          <button
            onClick={cycleModel}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/20 hover:bg-[var(--accent)]/20 transition-colors cursor-pointer"
            title="Click to switch model"
          >
            <Cpu size={10} /> {model}
          </button>
          <button
            onClick={cyclePermission}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold bg-[var(--surface2)] text-[var(--text2)] border border-[var(--border)] hover:border-[var(--accent)] hover:text-[var(--text)] transition-colors cursor-pointer"
            title="Click to switch permission mode"
          >
            <Shield size={10} /> {permission}
          </button>
        </div>

        {/* Autocomplete dropdown */}
        <Autocomplete
          isOpen={autocomplete.isOpen}
          items={autocomplete.items}
          selectedIndex={autocomplete.selectedIndex}
        />

        {/* Command menu */}
        <CommandMenu
          isOpen={commandMenu.isOpen}
          commands={commandMenu.commands}
          selectedIndex={commandMenu.selectedIndex}
        />

        {/* Input row */}
        <div className="flex items-center gap-2">
          <MicButton />
          <AttachButton onFileSelect={handleFileSelect} />
          <ImagePasteHandler onPaste={handleImagePaste} />

          <InputTextarea
            value={value}
            onChange={handleChange}
            onSubmit={handleSubmit}
            onKeyDown={handleKeyDown}
            disabled={false}
          />

          <SendButton
            isStreaming={isStreaming}
            disabled={!value.trim() && !isStreaming}
            onClick={handleSubmit}
          />
        </div>
      </div>
    </div>
  )
}
