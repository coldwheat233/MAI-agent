import { useState } from 'react'
import { Pencil, RotateCcw, Check, X, Repeat } from 'lucide-react'
import type { ChatMessage } from '@/types'
import { useChatStore } from '@/stores/chatStore'

interface UserMessageProps {
  message: ChatMessage
  onResubmit: (text: string, afterMsgId: string) => void
}

export function UserMessage({ message, onResubmit }: UserMessageProps) {
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(message.content)
  const updateUserMessage = useChatStore((s) => s.updateUserMessage)

  const handleSave = () => {
    const trimmed = editText.trim()
    if (!trimmed) return
    updateUserMessage(message.id, trimmed)
    setEditing(false)
  }

  const handleRerun = () => {
    onResubmit(message.content, message.id)
  }

  const handleEditResubmit = () => {
    const trimmed = editText.trim()
    if (!trimmed) return
    setEditing(false)
    // 不原地改历史气泡——追加新提问，保留原问答记录
    onResubmit(trimmed, message.id)
  }

  return (
    <div className="flex justify-end mb-4 animate-fade-in group">
      <div className="max-w-[82%]">
        {editing ? (
          <div className="flex flex-col gap-2">
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              className="w-full min-h-[60px] px-4 py-3 bg-[var(--user-bg)] border border-[var(--user-border)] rounded-xl text-[var(--text)] text-sm resize-none outline-none focus:border-[var(--accent)]"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleEditResubmit()
                }
                if (e.key === 'Escape') {
                  setEditText(message.content)
                  setEditing(false)
                }
              }}
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setEditText(message.content); setEditing(false) }}
                className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-md bg-[var(--surface2)] text-[var(--text2)] hover:text-[var(--text)]"
              >
                <X size={12} /> Cancel
              </button>
              <button
                onClick={handleEditResubmit}
                className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-md bg-[var(--accent)] text-white hover:opacity-90"
              >
                <Check size={12} /> Save & Send
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* 重发标记：让"新追加的一轮"和"原始提问"在视觉上区分开，
                避免误以为最近一条消息被覆盖。 */}
            {message.rerunOf && (
              <div className="flex items-center justify-end gap-1 mb-1 text-[10px] text-[var(--text3)]">
                <Repeat size={10} />
                <span>重发 · 追加为新的一轮</span>
              </div>
            )}
            <div className="bg-[var(--user-bg)] border border-[var(--user-border)] rounded-xl rounded-br-sm px-4 py-2.5 text-sm text-[var(--text)] whitespace-pre-wrap break-words">
              {message.content}
            </div>
            <div className="flex justify-end gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                onClick={() => setEditing(true)}
                className="p-1 rounded hover:bg-[var(--surface2)] text-[var(--text3)] hover:text-[var(--text2)]"
                title="Edit"
              >
                <Pencil size={13} />
              </button>
              <button
                onClick={handleRerun}
                className="p-1 rounded hover:bg-[var(--surface2)] text-[var(--text3)] hover:text-[var(--text2)]"
                title="Re-run"
              >
                <RotateCcw size={13} />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
