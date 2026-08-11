import { useMemo } from 'react'
import Markdown from 'markdown-to-jsx'
import { CodeBlock } from './CodeBlock'

interface MarkdownRendererProps {
  content: string
  className?: string
}

export function MarkdownRenderer({ content, className = '' }: MarkdownRendererProps) {
  const options = useMemo(() => ({
    overrides: {
      code: {
        component: ({ className: codeClassName, children }: any) => {
          const language = codeClassName?.replace('language-', '') || ''
          const code = typeof children === 'string' ? children : String(children || '')
          // Inline code (no language class from markdown parsing = inline)
          if (!codeClassName && !code.includes('\n')) {
            return (
              <code className="px-1.5 py-0.5 rounded text-[0.875em] bg-[var(--surface2)] text-[var(--text)] font-mono">
                {code}
              </code>
            )
          }
          return <CodeBlock code={code} language={language} />
        },
      },
      pre: {
        component: ({ children }: any) => <>{children}</>,
      },
      a: {
        component: ({ href, children }: any) => (
          <a href={href} className="text-[var(--accent)] hover:underline" target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
      },
      table: {
        component: ({ children }: any) => (
          <div className="overflow-x-auto my-3">
            <table className="min-w-full border-collapse border border-[var(--border)] text-sm">
              {children}
            </table>
          </div>
        ),
      },
      th: {
        component: ({ children }: any) => (
          <th className="border border-[var(--border)] px-3 py-2 bg-[var(--surface2)] font-semibold text-left">
            {children}
          </th>
        ),
      },
      td: {
        component: ({ children }: any) => (
          <td className="border border-[var(--border)] px-3 py-2">{children}</td>
        ),
      },
    },
  }), [])

  return (
    <div className={`chat-prose text-[var(--text)] leading-relaxed ${className}`}>
      <Markdown options={options}>{content}</Markdown>
    </div>
  )
}
