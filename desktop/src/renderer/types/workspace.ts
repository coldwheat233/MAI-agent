// ── Workspace Types ─────────────────────────────

export interface WorkspaceInfo {
  cwd: string
  name: string
  session_count?: number
  workspaces?: WorkspaceEntry[]
  sessions?: any[]
}

export interface WorkspaceEntry {
  slug?: string
  path: string
  session_count?: number
  updated_at?: string
}

export interface BrowseEntry {
  name: string
  path: string
  is_dir: boolean
}

export interface BrowseResult {
  path: string
  parent: string | null
  entries: BrowseEntry[]
}
