import { useCallback, useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { highlightCode } from '@/lib/markdown'

interface CodeBlockProps {
  code: string
  language?: string
}

export function CodeBlock({ code, language }: CodeBlockProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }, [code])

  const highlighted = highlightCode(code, language)

  return (
    <div className="relative group my-3">
      {language && (
        <span className="absolute top-2 left-3 text-[10px] font-semibold uppercase tracking-wider text-[var(--text3)] select-none">
          {language}
        </span>
      )}
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 px-2 py-1 text-[11px] rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text2)] opacity-0 group-hover:opacity-100 transition-opacity hover:text-[var(--text)] hover:border-[var(--text3)] flex items-center gap-1"
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
        {copied ? 'Copied' : 'Copy'}
      </button>
      <pre className="!bg-[var(--surface2)] !p-4 !rounded-lg !overflow-x-auto !text-[13px] !leading-relaxed">
        <code
          className={`!bg-transparent !p-0 ${language ? `language-${language}` : ''}`}
          dangerouslySetInnerHTML={{ __html: highlighted }}
        />
      </pre>
    </div>
  )
}
