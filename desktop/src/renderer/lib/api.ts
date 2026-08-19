// ── REST API Client ─────────────────────────────
import { SERVER_URL } from './constants'
import type {
  SessionInfo,
  SessionDetail,
  ToolDefinition,
  SkillInfo,
  MemoryListResponse,
  GitStatus,
  WorkspaceInfo,
  WorkspaceEntry,
  BrowseResult,
  FeishuStatus,
  CoordinatorState,
  ProvidersResponse,
  ProviderInfo,
} from '@/types'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${SERVER_URL}${path}`)
  if (!res.ok) throw new Error(`API ${path}: ${res.status}`)
  return res.json()
}

async function post<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const res = await fetch(`${SERVER_URL}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`API ${path}: ${res.status}`)
  return res.json()
}

export const api = {
  // Tools
  fetchTools: () => get<ToolDefinition[]>('/api/tools'),

  // Sessions
  fetchSessions: () => get<SessionInfo[]>('/api/sessions'),
  fetchSession: (id: string) => get<SessionDetail>(`/api/sessions/${id}`),
  loadSession: (id: string) => post<{ loaded: boolean; cwd?: string }>(`/api/sessions/${id}/load`),
  restartEngine: () => post<{ session_id: string }>('/api/restart'),

  // Skills
  fetchSkills: () => get<SkillInfo[]>('/api/skills'),

  // Memories
  fetchMemories: () => get<MemoryListResponse>('/api/memories'),

  // Git
  fetchGitStatus: () => get<GitStatus>('/api/git'),

  // Workspace
  fetchWorkspace: () => get<WorkspaceInfo>('/api/workspace'),
  fetchWorkspaces: () => get<WorkspaceEntry[]>('/api/workspaces'),
  switchWorkspace: (cwd: string) =>
    post<{ cwd: string; session_id: string }>('/api/workspace', { cwd }),
  registerWorkspace: (cwd: string) =>
    post<{ registered: boolean; path: string }>('/api/workspaces/register', { cwd }),
  unregisterWorkspace: (cwd: string) =>
    fetch(`${SERVER_URL}/api/workspaces`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cwd }),
    }).then(r => r.json()),

  // Browse directory
  browseDirectory: (path: string) => get<BrowseResult>(`/api/browse?path=${encodeURIComponent(path)}`),

  // Settings
  setMode: (mode: string) => post<{ mode: string }>('/api/mode', { mode }),
  setModel: (model: string, provider?: string) =>
    post<{ model: string; provider: string; hot_swapped?: boolean }>('/api/model', { model, provider }),
  setBrain: (brain: string) => post<{ brain: string }>('/api/brain', { brain }),
  setSandbox: (mode: string) => post<{ sandbox: string }>('/api/sandbox', { mode }),

  // LLM Providers（对齐 DSH listProviders / discoverModels / provider 管理）
  fetchProviders: () => get<ProvidersResponse>('/api/providers'),
  discoverModels: (provider: string) =>
    post<{ provider: string; models: string[] }>('/api/models/discover', { provider }),
  createProvider: (data: {
    name: string; label?: string; base_url: string;
    protocol?: string; api_key?: string; models?: string[];
  }) => post<ProviderInfo>('/api/providers', data),
  updateProvider: (name: string, data: {
    label?: string; base_url?: string; protocol?: string;
    api_key?: string; models?: string[]; default_model?: string;
  }) => post<ProviderInfo>(`/api/providers/${encodeURIComponent(name)}`, data, 'PUT'),
  deleteProvider: (name: string) =>
    fetch(`${SERVER_URL}/api/providers/${encodeURIComponent(name)}`, { method: 'DELETE' })
      .then(r => r.json()),
  addProviderModel: (name: string, model: string) =>
    post<{ provider: string; models: string[] }>(`/api/providers/${encodeURIComponent(name)}/models`, { model }),

  // Coordinator
  fetchCoordinator: () => get<CoordinatorState>('/api/coordinator'),

  // Feishu
  fetchFeishuStatus: () => get<FeishuStatus>('/api/feishu/status'),

  // Stats
  fetchStats: () => get<any>('/api/stats'),
}
