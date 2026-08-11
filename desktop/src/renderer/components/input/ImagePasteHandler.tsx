import { useImagePaste } from '@/hooks/useImagePaste'

interface ImagePasteHandlerProps {
  onPaste: (file: File) => void
}

export function ImagePasteHandler({ onPaste }: ImagePasteHandlerProps) {
  useImagePaste({ onPaste, enabled: true })
  return null
}
