import { MarkdownRenderer } from './MarkdownRenderer'
import { ToolCard } from './ToolCard'
import { ThinkingIndicator } from './ThinkingIndicator'
import { StreamingCursor } from './StreamingCursor'
import { useChatStore } from '@/stores/chatStore'
import type { ChatMessage } from '@/types'

interface AssistantMessageProps {
  message: ChatMessage
}

export function AssistantMessage({ message }: AssistantMessageProps) {
  const { content, toolCalls, isStreaming, isThinking } = message
  const globalStreamingId = useChatStore((s) => s.streamingMsgId)
  const globalStreaming = useChatStore((s) => s.isStreaming)

  // Only the actively streaming message shows thinking/cursor
  const isActive = message.id === globalStreamingId && globalStreaming

  // Show thinking indicator only for the active streaming message
  if (isThinking && isActive && !content && (!toolCalls || toolCalls.length === 0)) {
    return <ThinkingIndicator />
  }

  // Show nothing for empty non-streaming messages
  if (!content && (!toolCalls || toolCalls.length === 0) && !isActive) {
    return null
  }

  return (
    <div className="mb-5 animate-fade-in">
      {/* Text content */}
      {content && (
        <div className={`${isActive ? 'border-l-2 border-[var(--accent)] pl-4' : 'pl-4 border-l-2 border-transparent'}`}>
          <MarkdownRenderer content={content} />
        </div>
      )}

      {/* Inline tool cards */}
      {toolCalls && toolCalls.length > 0 && (
        <div className="mt-2 pl-4 border-l-2 border-transparent">
          {toolCalls.map((tool) => (
            <ToolCard key={tool.id} tool={tool} />
          ))}
        </div>
      )}

      {/* Streaming cursor only for active message */}
      {isActive && <StreamingCursor />}
    </div>
  )
}
