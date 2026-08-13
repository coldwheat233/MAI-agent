import { useState, useEffect, useMemo } from 'react'
import { useUIStore } from '@/stores/uiStore'
import { useSessionStore } from '@/stores/sessionStore'
import { useChatStore } from '@/stores/chatStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { ContextMenu, type ContextMenuItem } from '@/components/common/ContextMenu'
import { ConfirmModal } from '@/components/common/ConfirmModal'
import { api } from '@/lib/api'
import {
  Plus, FolderPlus, ChevronRight, Folder, MessageSquare, Search, X,
  Trash2, PanelLeft, PanelLeftClose, GitBranch, BookOpen, Brain, Settings, GraduationCap,
} from 'lucide-react'
import type { SessionInfo } from '@/types'

export function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useUIStore((s) => s.toggleSidebar)
  const openPanel = useUIStore((s) => s.openPanel)
  const closePanel = useUIStore((s) => s.closePanel)
  const activePanel = useUIStore((s) => s.activePanel)
  const openSettings = useUIStore((s) => s.openSettings)

  const sessions = useSessionStore((s) => s.sessions)
  const loadingSessions = useSessionStore((s) => s.loadingSessions)
  const currentId = useSessionStore((s) => s.currentSessionId)
  const setCurrentSessionId = useSessionStore((s) => s.setCurrentSessionId)
  const setMessages = useChatStore((s) => s.setMessages)
  const fetchSessions = useSessionStore((s) => s.fetchSessions)
  const newSession = useSessionStore((s) => s.newSession)
  const deleteSession = useSessionStore((s) => s.deleteSession)
  const clearMessages = useChatStore((s) => s.clearMessages)

  const cwd = useWorkspaceStore((s) => s.cwd)
  const workspaces = useWorkspaceStore((s) => s.workspaces)
  const switchWorkspace = useWorkspaceStore((s) => s.switchWorkspace)
  const addWorkspace = useWorkspaceStore((s) => s.addWorkspace)

  // 手风琴：任意时刻只展开"当前工作区"（除非用户显式折叠）。
  const [sessionsExpanded, setSessionsExpanded] = useState(true)
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; items: ContextMenuItem[] } | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [searching, setSearching] = useState(false)

  useEffect(() => { fetchSessions() }, [cwd])

  const norm = (p: string) => p.replace(/\\/g, '/')
  const q = searchQuery.toLowerCase().trim()

  // Debounced content search
  useEffect(() => {
    if (!q || q.length < 2) { setSearchResults([]); return }
    setSearching(true)
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`http://localhost:8765/api/sessions/search?q=${encodeURIComponent(q)}`)
        if (res.ok) setSearchResults(await res.json())
      } catch { setSearchResults([]) }
      setSearching(false)
    }, 300)
    return () => { clearTimeout(timer); setSearching(false) }
  }, [q])

  // Build flat workspace list from backend workspaces (SQLite 权威源)
  const wsList = useMemo(() => {
    const seen = new Set<string>()
    const list: { path: string; name: string; isCurrent: boolean }[] = []
    for (const w of workspaces) {
      const p = w.path
      if (!p) continue
      const n = norm(p)
      if (seen.has(n)) continue
      seen.add(n)
      list.push({ path: p, name: p.split(/[\\/]/).pop() || p, isCurrent: norm(cwd) === n })
    }
    if (cwd) {
      const n = norm(cwd)
      if (!seen.has(n)) list.push({ path: cwd, name: cwd.split(/[\\/]/).pop() || cwd, isCurrent: true })
    }
    return list
  }, [workspaces, cwd])

  // Filter by search query
  const filteredWsList = q
    ? wsList.filter((ws) => {
        if (ws.name.toLowerCase().includes(q)) return true
        if (ws.path.toLowerCase().includes(q)) return true
        // Also check sessions in current workspace
        if (ws.isCurrent && sessions.some((s) => s.session_id.toLowerCase().includes(q))) return true
        return false
      })
    : wsList

  const filteredSessions = q
    ? sessions.filter((s) => s.session_id.toLowerCase().includes(q))
    : sessions

  const handleLoadSession = async (sessionId: string) => {
    setCurrentSessionId(sessionId)
    setSessionsExpanded(true)
    // 加载会话（后端会自动切换到 session 自己的工作区）
    let loadedCwd: string | undefined
    try {
      const res = await api.loadSession(sessionId)
      loadedCwd = res.cwd
    } catch { /* ignore */ }
    // 若后端切换了工作区，同步前端 workspace 状态
    if (loadedCwd && norm(loadedCwd) !== norm(useWorkspaceStore.getState().cwd)) {
      await useWorkspaceStore.getState().fetchWorkspace()
      fetchSessions()
    }
    try {
      const detail = await api.fetchSession(sessionId)
      if (detail.messages) {
        const msgs = detail.messages
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((m, i) => ({
            id: `hist_${sessionId}_${i}`,
            role: m.role as 'user' | 'assistant',
            content: m.content || '',
            timestamp: Date.now() - (detail.messages.length - i) * 1000,
            toolCalls: (m.tool_calls || []).map((tc, j) => ({
              id: `hist_tc_${i}_${j}`, name: tc.name, args: tc.args, status: 'ok' as const,
            })),
          }))
        setMessages(msgs)
      }
    } catch { /* ignore */ }
  }

  const handleNewSession = async (wsPath: string) => {
    if (wsPath !== cwd) await switchWorkspace(wsPath)
    clearMessages()
    setSessionsExpanded(true)
    await newSession()
    fetchSessions()
  }

  const handleDeleteSession = (id: string, name: string) => setDeleteTarget({ id, name })
  const confirmDeleteSession = async () => {
    if (!deleteTarget) return
    await deleteSession(deleteTarget.id)
    if (currentId === deleteTarget.id) clearMessages()
    setDeleteTarget(null)
    fetchSessions()
  }

  const handleBrowseNewProject = async () => {
    const folder = await window.electronAPI.selectFolder()
    if (folder) {
      await addWorkspace(folder)
      // 选完新工程——直接切过去，让用户立即能在新工程里对话
      await switchWorkspace(folder)
      setSessionsExpanded(true)
    }
  }

  const handleSwitchWorkspace = async (wsPath: string) => {
    if (norm(wsPath) === norm(cwd)) return
    clearMessages()
    setSwitching(true)
    setSessionsExpanded(true)
    try {
      await switchWorkspace(wsPath)
    } catch {
      // 切换失败不卡 spinner
    } finally {
      setSwitching(false)
    }
    fetchSessions()
  }

  const removeWorkspace = useWorkspaceStore((s) => s.removeWorkspace)

  const handleRemoveWorkspace = (wsPath: string) => {
    const normed = norm(wsPath)
    removeWorkspace(wsPath)
    if (normed === norm(cwd)) {
      // 删的是当前工作区——切到 workspaces 里剩下的第一个
      const remaining = useWorkspaceStore.getState().workspaces
        .filter((w) => norm(w.path) !== normed)
      if (remaining.length > 0) {
        handleSwitchWorkspace(remaining[0].path)
      } else {
        clearMessages()
        fetchSessions()
      }
    }
  }

  const toggleExpand = (_wsPath?: string) => {
    setSessionsExpanded((v) => !v)
  }

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setDragOver(true) }
  const handleDragLeave = () => setDragOver(false)
  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    const file = e.dataTransfer.items[0]?.getAsFile()
    if (file) {
      const path = (file as any).path
      if (path) {
        try { await api.browseDirectory(path) } catch { return }
        await addWorkspace(path)
        await switchWorkspace(path)
        setSessionsExpanded(true)
      }
    }
  }

  const handleWsContextMenu = (e: React.MouseEvent, wsPath: string) => {
    e.preventDefault()
    const isCurrent = norm(wsPath) === norm(cwd)
    setCtxMenu({ x: e.clientX, y: e.clientY, items: [
      { label: 'New Session', onClick: () => handleNewSession(wsPath) },
      ...(!isCurrent ? [{ label: 'Switch to Project', onClick: () => handleSwitchWorkspace(wsPath) }] : []),
      { label: 'Remove from list', onClick: () => handleRemoveWorkspace(wsPath), danger: true },
    ]})
  }

  const handleSessionContextMenu = (e: React.MouseEvent, s: SessionInfo) => {
    e.preventDefault()
    setCtxMenu({ x: e.clientX, y: e.clientY, items: [
      { label: 'Load', onClick: () => handleLoadSession(s.session_id) },
      { label: 'Delete', onClick: () => handleDeleteSession(s.session_id, s.session_id), danger: true },
    ]})
  }

  const iconClass = (p: string) =>
    `p-1.5 rounded-md transition-colors ${activePanel === p ? 'text-[var(--accent)] bg-[var(--accent)]/10' : 'text-[var(--text3)] hover:text-[var(--text2)] hover:bg-[var(--surface2)]'}`

  if (collapsed) {
    return (
      <div className="flex flex-col items-center w-[48px] bg-[var(--surface)] border-r border-[var(--border)] shrink-0 py-3 gap-2">
        <button onClick={toggleSidebar} className="p-1.5 rounded-md text-[var(--text3)] hover:text-[var(--text2)] hover:bg-[var(--surface2)]" title="Expand"><PanelLeft size={18} /></button>
        <button onClick={handleBrowseNewProject} className="p-2 rounded-lg bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20" title="New Project"><FolderPlus size={18} /></button>
      </div>
    )
  }

  return (
    <>
      <div
        className={`flex flex-col w-[260px] bg-[var(--surface)] border-r border-[var(--border)] shrink-0 ${dragOver ? 'ring-2 ring-[var(--accent)] ring-inset' : ''}`}
        onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}
      >
        {/* New Project + Search */}
        <div className="px-3 py-2 border-b border-[var(--border)] space-y-2">
          <button
            onClick={handleBrowseNewProject}
            className={`w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded-lg border-2 border-dashed text-xs font-medium transition-all ${
              dragOver ? 'border-[var(--accent)] bg-[var(--accent)]/5 text-[var(--accent)]' : 'border-[var(--border)] text-[var(--text3)] hover:border-[var(--accent)] hover:text-[var(--accent)]'
            }`}
          >
            <FolderPlus size={14} /> {dragOver ? 'Drop folder here' : 'New Project'}
          </button>

          {/* Search bar */}
          <div className="relative">
            <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text3)]" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search projects & sessions..."
              className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md pl-7 pr-6 py-1 text-[11px] text-[var(--text)] outline-none focus:border-[var(--accent)] placeholder:text-[var(--text3)]"
            />
            {searchQuery && (
              <button onClick={() => setSearchQuery('')} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[var(--text3)] hover:text-[var(--text)]">
                <X size={11} />
              </button>
            )}
          </div>
        </div>

        {/* Switching indicator */}
        {switching && (
          <div className="px-3 py-1.5 text-[10px] text-[var(--accent)] bg-[var(--accent)]/5 border-b border-[var(--border)] animate-pulse">
            Switching workspace...
          </div>
        )}

        {/* Workspace tree */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {/* Content search results */}
          {q && searchResults.length > 0 && (
            <div className="border-b border-[var(--border)]">
              <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-[var(--accent)]">
                Content matches ({searchResults.length})
              </div>
              {searchResults.slice(0, 10).map((r: any) => (
                <div
                  key={r.session_id}
                  className="px-3 py-2 hover:bg-[var(--surface2)] cursor-pointer border-b border-[var(--border)] last:border-b-0"
                  onClick={() => {
                  // r.workspace 现在是后端返回的真实路径（无需前端解码 slug）；
                  // loadSession 后端会自动切换到 session 自己的工作区
                  handleLoadSession(r.session_id)
                }}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <MessageSquare size={11} className="text-[var(--accent)] shrink-0" />
                    <span className="text-[11px] font-medium text-[var(--text)] truncate">{r.title || r.session_id}</span>
                  </div>
                  {r.matches?.slice(0, 2).map((m: string, i: number) => (
                    <div key={i} className="text-[10px] text-[var(--text3)] truncate ml-4 leading-relaxed">
                      {m}
                    </div>
                  ))}
                  <div className="text-[9px] text-[var(--text3)] mt-0.5 ml-4">
                    {r.workspace} · {r.message_count} msgs
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Searching indicator */}
          {q && searching && searchResults.length === 0 && (
            <div className="px-4 py-3 text-center text-[11px] text-[var(--text3)] animate-pulse">Searching...</div>
          )}

          {/* No results */}
          {q && !searching && searchResults.length === 0 && filteredWsList.length === 0 && (
            <div className="px-4 py-6 text-center text-[11px] text-[var(--text3)]">No results for "{searchQuery}"</div>
          )}

          {filteredWsList.map((ws) => {
            const isCurrent = ws.isCurrent
            const showSessions = isCurrent && sessionsExpanded
            const hasActiveSession = isCurrent && !!currentId && currentId !== 'default'

            return (
              <div key={ws.path} className="border-b border-[var(--border)] last:border-b-0">
                {/* Workspace header */}
                <div
                  className={`relative flex items-center gap-1.5 pl-3 pr-2 py-1.5 cursor-pointer transition-colors group ${
                    hasActiveSession
                      ? 'bg-[var(--accent)]/10'
                      : isCurrent
                      ? 'bg-[var(--accent)]/5'
                      : 'hover:bg-[var(--surface2)]'
                  } ${switching && isCurrent ? 'opacity-50' : ''}`}
                  onClick={() => { if (!isCurrent) handleSwitchWorkspace(ws.path); else toggleExpand() }}
                  onContextMenu={(e) => handleWsContextMenu(e, ws.path)}
                >
                  {/* 当前工作区左侧 accent 高亮条 */}
                  {isCurrent && (
                    <span className="absolute left-0 top-1 bottom-1 w-[3px] rounded-r bg-[var(--accent)]" />
                  )}
                  <ChevronRight size={13} className={`text-[var(--text3)] transition-transform shrink-0 ${showSessions ? 'rotate-90' : ''}`} />
                  <Folder size={13} className={`shrink-0 ${isCurrent ? 'text-[var(--accent)]' : 'text-[var(--text2)]'}`} />
                  <span className={`text-xs font-medium truncate flex-1 ${isCurrent ? 'text-[var(--accent)]' : 'text-[var(--text)]'}`}>
                    {ws.name}
                  </span>
                  {isCurrent && <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)] shrink-0" title="Active workspace" />}
                  {!isCurrent && <span className="text-[10px] text-[var(--text3)]">↗</span>}
                  <button
                    onClick={(e) => { e.stopPropagation(); handleNewSession(ws.path) }}
                    className="p-0.5 rounded text-[var(--text3)] hover:text-[var(--accent)] hover:bg-[var(--surface2)] opacity-0 group-hover:opacity-100 transition-opacity"
                    title="New session"
                  >
                    <Plus size={13} />
                  </button>
                </div>

                {/* Sessions — 只展示当前工作区的 session 列表；其他工作区的 session 隐藏 */}
                {showSessions && (
                  <div className="pb-1">
                    {loadingSessions && filteredSessions.length === 0 ? (
                      <div className="px-8 py-2 text-[10px] text-[var(--text3)]">Loading sessions...</div>
                    ) : filteredSessions.length === 0 ? (
                      <div className="px-8 py-2 text-[10px] text-[var(--text3)]">{q ? 'No matching sessions' : 'No sessions'}</div>
                    ) : (
                      filteredSessions.map((s) => (
                        <div
                          key={s.session_id}
                          onClick={() => handleLoadSession(s.session_id)}
                          onContextMenu={(e) => handleSessionContextMenu(e, s)}
                          className={`flex items-center gap-1.5 px-2 py-1.5 ml-4 rounded-md cursor-pointer transition-colors group ${
                            s.session_id === currentId
                              ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                              : 'text-[var(--text2)] hover:bg-[var(--surface2)] hover:text-[var(--text)]'
                          }`}
                        >
                          <MessageSquare size={12} className={`shrink-0 ${s.session_id === currentId ? 'text-[var(--accent)]' : 'text-[var(--text3)]'}`} />
                          <span className="text-[11px] truncate flex-1">{s.title || s.session_id}</span>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleDeleteSession(s.session_id, s.session_id) }}
                            className="p-0.5 rounded text-[var(--text3)] hover:text-[var(--red)] opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                          >
                            <Trash2 size={11} />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            )
          })}

          {wsList.length === 0 && !q && (
            <div className="px-4 py-8 text-center text-[11px] text-[var(--text3)]">
              No projects yet.<br />Click "New Project" or drag a folder here.
            </div>
          )}
        </div>

        {/* Bottom bar */}
        <div className="flex items-center gap-1 px-3 py-2 border-t border-[var(--border)] shrink-0">
          <button onClick={() => activePanel === 'memory' ? closePanel() : openPanel('memory')} className={iconClass('memory')} title="Memory"><Brain size={16} /></button>
          <button onClick={() => activePanel === 'skills' ? closePanel() : openPanel('skills')} className={iconClass('skills')} title="Skills"><BookOpen size={16} /></button>
          <button onClick={() => activePanel === 'learning' ? closePanel() : openPanel('learning')} className={iconClass('learning')} title="Learning Queue"><GraduationCap size={16} /></button>
          <button onClick={() => activePanel === 'git' ? closePanel() : openPanel('git')} className={iconClass('git')} title="Git"><GitBranch size={16} /></button>
          <button onClick={openSettings} className="p-1.5 rounded-md text-[var(--text3)] hover:text-[var(--text2)] hover:bg-[var(--surface2)] ml-auto" title="Settings"><Settings size={16} /></button>
          <button onClick={toggleSidebar} className="p-1.5 rounded-md text-[var(--text3)] hover:text-[var(--text2)] hover:bg-[var(--surface2)]" title="Collapse"><PanelLeftClose size={16} /></button>
        </div>
      </div>

      {ctxMenu && <ContextMenu x={ctxMenu.x} y={ctxMenu.y} items={ctxMenu.items} onClose={() => setCtxMenu(null)} />}
      <ConfirmModal open={deleteTarget !== null} title="Delete Session" message={`确定要删除 "${deleteTarget?.name}" 吗？此操作不可撤销。`} confirmLabel="Delete" onConfirm={confirmDeleteSession} onCancel={() => setDeleteTarget(null)} />
    </>
  )
}
