// ── Autocomplete Hook ───────────────────────────
import { useState, useCallback, useRef } from 'react'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useMemoryStore } from '@/stores/memoryStore'

export interface AutocompleteItem {
  label: string
  insert: string
  type: 'file' | 'memory'
}

export function useAutocomplete() {
  const [isOpen, setIsOpen] = useState(false)
  const [items, setItems] = useState<AutocompleteItem[]>([])
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [matchType, setMatchType] = useState<'file' | 'memory' | null>(null)
  const [matchStart, setMatchStart] = useState(0)
  const [matchText, setMatchText] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()
  const lastQueryRef = useRef('')

  const browseDirectory = useWorkspaceStore((s) => s.browseDirectory)
  const browseEntries = useWorkspaceStore((s) => s.browseEntries)
  const memories = useMemoryStore((s) => s.memories)

  const detect = useCallback((value: string, cursorPos: number) => {
    // Find the last @ before cursor
    const beforeCursor = value.slice(0, cursorPos)
    const atIndex = beforeCursor.lastIndexOf('@')

    if (atIndex === -1) {
      setIsOpen(false)
      setMatchType(null)
      return
    }

    // @ must be preceded by space or start of text
    if (atIndex > 0 && beforeCursor[atIndex - 1] !== ' ' && beforeCursor[atIndex - 1] !== '\n') {
      setIsOpen(false)
      setMatchType(null)
      return
    }

    const query = beforeCursor.slice(atIndex + 1)
    setMatchStart(atIndex)
    setMatchText(query)

    // Memory autocomplete: @memory:xxx
    if (query.startsWith('memory:')) {
      const memQuery = query.slice(7).toLowerCase()
      const filtered = memories
        .filter((m) =>
          m.name.toLowerCase().includes(memQuery) ||
          m.description.toLowerCase().includes(memQuery)
        )
        .slice(0, 8)
        .map((m) => ({
          label: `${m.name} — ${m.description.slice(0, 40)}`,
          insert: `[[${m.name}]]`,
          type: 'memory' as const,
        }))
      setItems(filtered)
      setSelectedIndex(0)
      setIsOpen(filtered.length > 0)
      setMatchType('memory')
      return
    }

    // File autocomplete: @partial/path
    if (query.includes('memory:')) {
      setIsOpen(false)
      return
    }

    // Look up current workspace entries for file matching
    const fileQuery = query.toLowerCase()
    const filtered = browseEntries
      .filter((e) => e.name.toLowerCase().includes(fileQuery))
      .slice(0, 8)
      .map((e) => ({
        label: `${e.is_dir ? '📁' : '📄'} ${e.name}`,
        insert: e.path,
        type: 'file' as const,
      }))

    // Immediate display from cached entries
    setItems(filtered)
    setSelectedIndex(0)
    setIsOpen(filtered.length > 0)
    setMatchType('file')

    // Debounced server fetch for more results
    lastQueryRef.current = query
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      if (lastQueryRef.current !== query) return // query changed
      try {
        const dir = query.includes('/') || query.includes('\\')
          ? query.replace(/[^/\\]*$/, '') || '.'
          : '.'
        await browseDirectory(dir)
        // After fetching, re-filter with new entries
        const freshEntries = useWorkspaceStore.getState().browseEntries
        const fileQueryF = query.split(/[\\/]/).pop()?.toLowerCase() || query.toLowerCase()
        const freshFiltered = freshEntries
          .filter((e) => e.name.toLowerCase().includes(fileQueryF))
          .slice(0, 8)
          .map((e) => ({
            label: `${e.is_dir ? '📁' : '📄'} ${e.name}`,
            insert: e.path,
            type: 'file' as const,
          }))
        // Only update if query still matches
        if (lastQueryRef.current === query) {
          setItems(freshFiltered)
          setIsOpen(freshFiltered.length > 0)
        }
      } catch {
        // server fetch failed, keep cached results
      }
    }, 200)
  }, [browseDirectory, browseEntries, memories])

  const select = useCallback((): { replacement: string; start: number; end: number } | null => {
    if (!isOpen || items.length === 0) return null
    const item = items[selectedIndex]
    if (!item) return null

    setIsOpen(false)
    setMatchType(null)

    return {
      replacement: item.insert,
      start: matchStart,
      end: matchStart + matchText.length + 1,
    }
  }, [isOpen, items, selectedIndex, matchStart, matchText.length])

  const moveDown = useCallback(() => {
    setSelectedIndex((i) => Math.min(i + 1, items.length - 1))
  }, [items.length])

  const moveUp = useCallback(() => {
    setSelectedIndex((i) => Math.max(i - 1, 0))
  }, [])

  const close = useCallback(() => {
    setIsOpen(false)
    setMatchType(null)
  }, [])

  return {
    isOpen,
    items,
    selectedIndex,
    matchType,
    detect,
    select,
    moveDown,
    moveUp,
    close,
  }
}
