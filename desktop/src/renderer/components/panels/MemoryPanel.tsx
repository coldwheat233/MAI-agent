import { useEffect, useMemo } from 'react'
import { useMemoryStore } from '@/stores/memoryStore'
import { ArrowLeft, Tag, BookOpen } from 'lucide-react'

export function MemoryPanel() {
  const {
    memories, tags, selectedTag, selectedMemory,
    searchQuery, fetchMemories,
    selectTag, selectMemory, setSearchQuery,
  } = useMemoryStore()

  useEffect(() => {
    fetchMemories()
  }, [])

  const filtered = useMemo(() => {
    let result = memories
    if (selectedTag) {
      result = result.filter((m) => m.tags?.includes(selectedTag))
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter(
        (m) => m.name.toLowerCase().includes(q) || m.description.toLowerCase().includes(q)
      )
    }
    return result
  }, [memories, selectedTag, searchQuery])

  // Memory detail view
  if (selectedMemory) {
    return (
      <div className="p-4 animate-fade-in">
        <button
          onClick={() => selectMemory(null)}
          className="flex items-center gap-1 text-xs text-[var(--accent)] hover:underline mb-4"
        >
          <ArrowLeft size={13} /> Back to list
        </button>
        <h4 className="text-sm font-bold text-[var(--text)] mb-1">{selectedMemory.name}</h4>
        <p className="text-xs text-[var(--text2)] leading-relaxed whitespace-pre-wrap mb-3">
          {selectedMemory.description}
        </p>
        <div className="flex flex-wrap gap-1 mb-3">
          {selectedMemory.tags?.map((tag) => (
            <span key={tag} className="px-2 py-0.5 rounded text-[10px] bg-[var(--accent)]/10 text-[var(--accent)]">
              {tag}
            </span>
          ))}
        </div>
        <div className="text-[10px] text-[var(--text3)]">
          Type: {selectedMemory.type || '—'} · Created: {selectedMemory.created_at || '—'}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Search */}
      <div className="px-4 py-3 border-b border-[var(--border)]">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search memories..."
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-3 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)] placeholder:text-[var(--text3)]"
        />
      </div>

      {/* Tag chips */}
      {tags.length > 0 && (
        <div className="px-4 py-2 border-b border-[var(--border)] flex flex-wrap gap-1">
          <button
            onClick={() => selectTag(null)}
            className={`px-2 py-0.5 rounded-full text-[10px] font-medium transition-colors ${
              !selectedTag
                ? 'bg-[var(--accent)] text-white'
                : 'bg-[var(--surface2)] text-[var(--text2)] hover:text-[var(--text)]'
            }`}
          >
            All
          </button>
          {tags.map((tag) => (
            <button
              key={tag}
              onClick={() => selectTag(selectedTag === tag ? null : tag)}
              className={`px-2 py-0.5 rounded-full text-[10px] font-medium transition-colors ${
                selectedTag === tag
                  ? 'bg-[var(--accent)] text-white'
                  : 'bg-[var(--surface2)] text-[var(--text2)] hover:text-[var(--text)]'
              }`}
            >
              {tag}
            </button>
          ))}
        </div>
      )}

      {/* Memory list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-[var(--text3)]">
            <BookOpen size={24} className="mx-auto mb-2 text-[var(--border)]" />
            No memories found
          </div>
        ) : (
          filtered.map((mem) => (
            <button
              key={mem.name}
              onClick={() => selectMemory(mem)}
              className="w-full text-left px-4 py-3 border-b border-[var(--border)] hover:bg-[var(--surface2)] transition-colors"
            >
              <div className="flex items-center gap-2 mb-0.5">
                <Tag size={13} className="text-[var(--accent)] shrink-0" />
                <span className="text-[13px] font-medium text-[var(--text)] truncate">{mem.name}</span>
              </div>
              <p className="text-[11px] text-[var(--text2)] truncate ml-5">{mem.description}</p>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
