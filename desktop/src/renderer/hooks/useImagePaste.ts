// ── Image Paste Hook ────────────────────────────
import { useEffect } from 'react'

interface UseImagePasteOptions {
  onPaste: (file: File) => void
  enabled?: boolean
}

export function useImagePaste({ onPaste, enabled = true }: UseImagePasteOptions) {
  useEffect(() => {
    if (!enabled) return

    const handler = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items
      if (!items) return

      for (let idx = 0; idx < items.length; idx++) {
        const item = items[idx];
        if (item.type.startsWith('image/')) {
          const file = item.getAsFile()
          if (file) {
            onPaste(file)
          }
        }
      }
    }

    document.addEventListener('paste', handler)
    return () => document.removeEventListener('paste', handler)
  }, [onPaste, enabled])
}
