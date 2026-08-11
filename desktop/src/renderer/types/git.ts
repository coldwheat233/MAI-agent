// ── Git Status Types ────────────────────────────

export interface GitStatus {
  is_repo: boolean
  branch: string
  status: string
  recent_commits: string
}
