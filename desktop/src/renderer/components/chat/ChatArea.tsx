import { useChatStore } from '@/stores/chatStore'
import { useAutoScroll } from '@/hooks/useAutoScroll'
import { UserMessage } from './UserMessage'
import { AssistantMessage } from './AssistantMessage'
import { EmptyState } from './EmptyState'
import { useCallback } from 'react'

interface ChatAreaProps {
  onPromptSubmit: (text: string) => void
  onResubmit: (text: string, afterMsgId: string) => void
}

export function ChatArea({ onPromptSubmit, onResubmit }: ChatAreaProps) {
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)

  const { containerRef, handleScroll } = useAutoScroll(messages.length)

  const handleResubmit = useCallback((text: string, afterMsgId: string) => {
    onResubmit(text, afterMsgId)
  }, [onResubmit])

  const isEmpty = messages.length === 0 && !isStreaming

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto px-6 py-4"
    >
      {isEmpty ? (
        <EmptyState onPromptClick={onPromptSubmit} />
      ) : (
        <div className="max-w-3xl mx-auto">
          {messages.map((msg) =>
            msg.role === 'user' ? (
              <UserMessage
                key={msg.id}
                message={msg}
                onResubmit={(text, afterMsgId) => handleResubmit(text, afterMsgId)}
              />
            ) : (
              <AssistantMessage key={msg.id} message={msg} />
            )
          )}
        </div>
      )}
    </div>
  )
}
