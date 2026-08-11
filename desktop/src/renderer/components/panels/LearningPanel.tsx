import { useEffect, useState } from 'react'
import { BookOpen, Plus, Trash2, CheckCircle, Clock, GraduationCap, RefreshCw } from 'lucide-react'

interface LearningItem {
  id: string
  concept: string
  context: string
  priority: string
  status: string
  notes: string
  created_at: string
  learned_at: string | null
  feishu_doc_token: string | null
}

const API = 'http://localhost:8765/api/learning-queue'
const priorityLabel: Record<string, string> = { high: '高', medium: '中', low: '低' }

export function LearningPanel() {
  const [items, setItems] = useState<LearningItem[]>([])
  const [stats, setStats] = useState<any>({})
  const [showAdd, setShowAdd] = useState(false)
  const [newConcept, setNewConcept] = useState('')
  const [newContext, setNewContext] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editNotes, setEditNotes] = useState('')
  const [syncingId, setSyncingId] = useState<string | null>(null)

  const fetchItems = async () => {
    try {
      const res = await fetch(API)
      const data = await res.json()
      setItems(data.items || [])
      setStats(data.stats || {})
    } catch { /* ignore */ }
  }

  useEffect(() => { fetchItems() }, [])

  const handleAdd = async () => {
    if (!newConcept.trim()) return
    await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ concept: newConcept, context: newContext, priority: 'medium' }),
    })
    setNewConcept(''); setNewContext(''); setShowAdd(false)
    fetchItems()
  }

  const handleDelete = async (id: string) => {
    await fetch(`${API}/${id}`, { method: 'DELETE' })
    fetchItems()
  }

  const handleMarkLearned = async (id: string) => {
    await fetch(`${API}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'learned' }),
    })
    fetchItems()
  }

  const handleSaveNotes = async (id: string) => {
    await fetch(`${API}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes: editNotes, status: 'learned' }),
    })
    setEditingId(null); setEditNotes('')
    fetchItems()
  }

  const handleSyncToFeishu = async (id: string) => {
    setSyncingId(id)
    await fetch(`${API}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'learned' }),
    })
    setSyncingId(null)
    fetchItems()
  }

  const pending = items.filter((i) => i.status === 'pending')
  const learned = items.filter((i) => i.status === 'learned' || i.status === 'synced')

  const priorityColor = (p: string) =>
    p === 'high' ? 'text-[var(--red)]' : p === 'medium' ? 'text-[var(--yellow)]' : 'text-[var(--text3)]'

  return (
    <div className="flex flex-col h-full">
      {/* 统计 */}
      <div className="px-4 py-3 border-b border-[var(--border)] flex items-center gap-3">
        <div className="flex-1 flex gap-3 text-xs">
          <span className="text-[var(--yellow)]">📋 {stats.pending || 0} 待学</span>
          <span className="text-[var(--green)]">✅ {stats.learned || 0} 已学</span>
          <span className="text-[var(--accent)]">📤 {stats.synced || 0} 已同步</span>
        </div>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="p-1.5 rounded-md text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
          title="添加概念"
        >
          <Plus size={16} />
        </button>
      </div>

      {/* 添加表单 */}
      {showAdd && (
        <div className="px-4 py-3 border-b border-[var(--border)] bg-[var(--surface2)] space-y-2 animate-fade-in">
          <input
            type="text" value={newConcept} onChange={(e) => setNewConcept(e.target.value)}
            placeholder="概念名（如 RAFT 共识算法）..."
            className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-3 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)]"
            onKeyDown={(e) => { if (e.key === 'Enter') handleAdd() }}
            autoFocus
          />
          <input
            type="text" value={newContext} onChange={(e) => setNewContext(e.target.value)}
            placeholder="来源上下文（在哪里遇到的）..."
            className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-3 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)]"
            onKeyDown={(e) => { if (e.key === 'Enter') handleAdd() }}
          />
          <button onClick={handleAdd} className="w-full py-1.5 bg-[var(--accent)] text-white rounded-md text-xs font-medium">
            添加到队列
          </button>
        </div>
      )}

      {/* 队列列表 */}
      <div className="flex-1 overflow-y-auto">
        {/* 待学 */}
        {pending.length > 0 && (
          <div>
            <div className="px-4 py-2 text-[10px] font-bold uppercase tracking-wider text-[var(--text3)] flex items-center gap-1.5">
              <Clock size={11} /> 待学习
            </div>
            {pending.map((item) => (
              <div key={item.id} className="px-4 py-2.5 border-b border-[var(--border)] hover:bg-[var(--surface2)] transition-colors">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium text-[var(--text)]">{item.concept}</div>
                    {item.context && <div className="text-[10px] text-[var(--text3)] mt-0.5 truncate">{item.context}</div>}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <span className={`text-[10px] font-semibold ${priorityColor(item.priority)}`}>{priorityLabel[item.priority] || item.priority}</span>
                    <button onClick={() => handleMarkLearned(item.id)} className="p-1 rounded text-[var(--text3)] hover:text-[var(--green)] hover:bg-[var(--surface2)]" title="标记已学">
                      <CheckCircle size={14} />
                    </button>
                    <button onClick={() => handleDelete(item.id)} className="p-1 rounded text-[var(--text3)] hover:text-[var(--red)] hover:bg-[var(--surface2)]" title="删除">
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 已学 */}
        {learned.length > 0 && (
          <div>
            <div className="px-4 py-2 text-[10px] font-bold uppercase tracking-wider text-[var(--text3)] flex items-center gap-1.5">
              <GraduationCap size={11} /> 已学习
            </div>
            {learned.map((item) => (
              <div key={item.id} className="px-4 py-2.5 border-b border-[var(--border)]">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium text-[var(--text2)] line-through opacity-70">{item.concept}</div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {item.status === 'synced' ? (
                      <span className="text-[10px] text-[var(--accent)] font-semibold">📤 已同步</span>
                    ) : (
                      <>
                        <button onClick={() => { setEditingId(item.id); setEditNotes(item.notes || '') }} className="p-1 rounded text-[var(--text3)] hover:text-[var(--accent)]" title="添加笔记">
                          <BookOpen size={13} />
                        </button>
                        <button
                          onClick={() => handleSyncToFeishu(item.id)}
                          disabled={syncingId === item.id}
                          className="p-1 rounded text-[var(--text3)] hover:text-[var(--accent)] disabled:opacity-50"
                          title="同步到飞书"
                        >
                          <RefreshCw size={13} className={syncingId === item.id ? 'animate-spin' : ''} />
                        </button>
                      </>
                    )}
                    <button onClick={() => handleDelete(item.id)} className="p-1 rounded text-[var(--text3)] hover:text-[var(--red)]" title="删除">
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>

                {/* 笔记编辑器 */}
                {editingId === item.id && (
                  <div className="mt-2 space-y-1.5 animate-fade-in">
                    <textarea
                      value={editNotes}
                      onChange={(e) => setEditNotes(e.target.value)}
                      placeholder="学习笔记..."
                      rows={3}
                      className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-3 py-1.5 text-[11px] text-[var(--text)] outline-none focus:border-[var(--accent)] resize-none"
                    />
                    <div className="flex justify-end gap-1.5">
                      <button onClick={() => { setEditingId(null); setEditNotes('') }} className="px-2 py-1 text-[10px] text-[var(--text3)] hover:text-[var(--text)]">取消</button>
                      <button onClick={() => handleSaveNotes(item.id)} className="px-2 py-1 text-[10px] bg-[var(--accent)] text-white rounded">保存</button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {items.length === 0 && (
          <div className="px-4 py-8 text-center">
            <BookOpen size={24} className="mx-auto mb-2 text-[var(--border)]" />
            <div className="text-[11px] text-[var(--text3)]">暂无待学概念</div>
            <div className="text-[10px] text-[var(--text3)] mt-1">添加开发过程中遇到的新概念</div>
          </div>
        )}
      </div>
    </div>
  )
}
