// ── Constants ───────────────────────────────────

export const SERVER_URL = 'http://localhost:8765'

export const DEFAULT_MODEL = 'deepseek-v4-pro'
export const DEFAULT_PERMISSION = 'auto' as const
export const DEFAULT_THEME = 'dark' as const
export const DEFAULT_LANGUAGE = 'zh' as const

export const MODELS = ['deepseek-v4-pro', 'deepseek-chat', 'deepseek-reasoner']

export const PERMISSION_OPTIONS = [
  { value: 'auto', label: { zh: '自动执行', en: 'Auto' } },
  { value: 'manual', label: { zh: '手动确认', en: 'Manual' } },
  { value: 'plan', label: { zh: '只读计划', en: 'Plan' } },
] as const

export const EXAMPLE_PROMPTS = {
  zh: [
    '帮我写一个 Python FastAPI 的 CRUD 接口',
    '分析当前项目的代码结构和依赖关系',
    '帮我重构 src/utils.py，提高可读性',
  ],
  en: [
    'Write a Python FastAPI CRUD endpoint for me',
    'Analyze the code structure and dependencies of this project',
    'Help me refactor src/utils.py for better readability',
  ],
} as const

export const TOOL_DISPLAY_CONFIG: Record<string, { icon: string; label: string }> = {
  Read: { icon: '📖', label: 'Read' },
  Write: { icon: '✏️', label: 'Write' },
  Edit: { icon: '📝', label: 'Edit' },
  Bash: { icon: '⚡', label: 'Bash' },
  Grep: { icon: '🔍', label: 'Grep' },
  Glob: { icon: '📂', label: 'Glob' },
  WebSearch: { icon: '🌐', label: 'WebSearch' },
  WebFetch: { icon: '📡', label: 'WebFetch' },
  Agent: { icon: '🤖', label: 'Agent' },
  TaskCreate: { icon: '📋', label: 'Task' },
  TodoWrite: { icon: '✅', label: 'Todo' },
  AskUserQuestion: { icon: '❓', label: 'Ask' },
  NotebookEdit: { icon: '📓', label: 'Notebook' },
  SendMessage: { icon: '📨', label: 'Send' },
  CronCreate: { icon: '⏰', label: 'Cron' },
  GitStatus: { icon: '🌿', label: 'Git' },
  GitDiff: { icon: '📊', label: 'Diff' },
  GitCommit: { icon: '💾', label: 'Commit' },
  GitPush: { icon: '🚀', label: 'Push' },
  Skill: { icon: '🧠', label: 'Skill' },
  Workflow: { icon: '🔄', label: 'Workflow' },
  MemoryRead: { icon: '📚', label: 'Memory' },
  MemoryWrite: { icon: '✍️', label: 'Memory' },
  EnterWorktree: { icon: '🌲', label: 'Worktree' },
  FeishuSearch: { icon: '🏮', label: 'Feishu' },
  DeployPlan: { icon: '🚢', label: 'Deploy' },
}

export const MAX_TEXTAREA_ROWS = 6
export const RECONNECT_BASE_MS = 1000
export const RECONNECT_MAX_MS = 30000
