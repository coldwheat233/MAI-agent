// ── Memory Types ────────────────────────────────

export interface TaggedMemory {
  name: string
  description: string
  type: string
  tags: string[]
  created_at?: string
  wiki_links?: string[]
}

export interface MemoryListResponse {
  memories: TaggedMemory[]
  tags: string[]
}
