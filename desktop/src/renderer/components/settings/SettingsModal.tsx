import { useState } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import { useUIStore } from '@/stores/uiStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { Modal } from '@/components/common/Modal'
import type { Theme, Language, ProviderInfo } from '@/types'
import { FolderOpen, ChevronRight } from 'lucide-react'
import { SERVER_URL } from '@/lib/constants'
import { api } from '@/lib/api'

export function SettingsModal() {
  const open = useUIStore((s) => s.isSettingsOpen)
  const close = useUIStore((s) => s.closeSettings)
  const currentLang = useSettingsStore((s) => s.language)

  const t = (zh: string, en: string) => (currentLang === 'zh' ? zh : en)

  return (
    <Modal open={open} onClose={close} title={t('设置', 'Settings')} maxWidth="max-w-md">
      <div className="space-y-6">
        <ModelSection />
        <ThemeSection />
        <LanguageSection />
        <WorkspaceSection />
        <FeishuSection />
      </div>
    </Modal>
  )
}

// ── Model / Provider（对齐 DSH provider 管理 UI）──────────

function ModelSection() {
  const lang = useSettingsStore((s) => s.language)
  const model = useSettingsStore((s) => s.model)
  const provider = useSettingsStore((s) => s.provider)
  const providers = useSettingsStore((s) => s.providers)
  const setModel = useSettingsStore((s) => s.setModel)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  const currentProvider = providers.find(p => p.name === provider)
  const availableModels = currentProvider?.models || []

  const handleProviderChange = (name: string) => {
    const p = providers.find(x => x.name === name)
    if (!p) return
    setModel(p.default_model || p.models[0] || '', p.name)
  }

  return (
    <Section label={lang === 'zh' ? '模型 / Model' : 'Model'}>
      {/* 提供方列表（DSH: Provider 列表，点击展开编辑） */}
      <div className="space-y-1 mb-3">
        {providers.map((p) => (
          <div key={p.name} className="rounded-lg border border-[var(--border)] overflow-hidden">
            <button
              onClick={() => {
                setExpanded(expanded === p.name ? null : p.name)
                if (provider !== p.name) handleProviderChange(p.name)
              }}
              className={`w-full flex items-center gap-2 px-3 py-2 text-left transition-colors ${
                provider === p.name ? 'bg-[var(--accent)]/10' : 'hover:bg-[var(--surface2)]'
              }`}
            >
              <span className={`text-xs font-medium truncate flex-1 ${provider === p.name ? 'text-[var(--accent)]' : 'text-[var(--text)]'}`}>
                {p.label}
                {p.is_custom && <span className="ml-1 text-[9px] text-[var(--text3)]">(custom)</span>}
              </span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${p.has_key ? 'bg-emerald-500/10 text-emerald-500' : 'bg-[var(--surface2)] text-[var(--text3)]'}`}>
                {p.has_key ? 'key ✓' : 'no key'}
              </span>
              <ChevronRight size={12} className={`text-[var(--text3)] transition-transform ${expanded === p.name ? 'rotate-90' : ''}`} />
            </button>
            {expanded === p.name && (
              <ProviderEdit
                info={p}
                lang={lang}
                onSaved={() => { setExpanded(null); useSettingsStore.getState().fetchProviders() }}
                onDeleted={() => { setExpanded(null); useSettingsStore.getState().fetchProviders() }}
              />
            )}
          </div>
        ))}
      </div>

      {/* 添加提供方 */}
      {adding ? (
        <ProviderCreateForm
          lang={lang}
          onCreated={(name) => {
            setAdding(false)
            useSettingsStore.getState().fetchProviders().then(() => handleProviderChange(name))
          }}
          onCancel={() => setAdding(false)}
        />
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="w-full py-2 rounded-lg border border-dashed border-[var(--border)] text-xs text-[var(--text3)] hover:text-[var(--text)] hover:border-[var(--accent)] transition-colors"
        >
          + {lang === 'zh' ? '添加提供方' : 'Add Provider'}
        </button>
      )}

      {/* 当前模型显示（热切换） */}
      <div className="mt-3 flex items-center gap-2">
        <select
          value={model}
          onChange={(e) => setModel(e.target.value, provider)}
          className="flex-1 bg-[var(--bg)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
        >
          {availableModels.length === 0 && <option value="">—</option>}
          {availableModels.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>
      <p className="mt-1 text-[10px] text-[var(--text3)]">
        {lang === 'zh' ? '切换模型为热切换，不丢上下文' : 'Model switch is hot-swap, keeps context'}
      </p>
    </Section>
  )
}

// ── Provider 编辑（API 密钥 + 自定义设置 + 模型目录）──

function ProviderEdit({ info, lang, onSaved, onDeleted }: {
  info: ProviderInfo; lang: Language; onSaved: () => void; onDeleted: () => void
}) {
  const [apiKey, setApiKey] = useState('')
  const [label, setLabel] = useState(info.label)
  const [baseUrl, setBaseUrl] = useState(info.base_url)
  const [models, setModels] = useState(info.models)
  const [saving, setSaving] = useState(false)
  const [discovering, setDiscovering] = useState(false)
  const [newModel, setNewModel] = useState('')
  const [msg, setMsg] = useState('')

  const handleSave = async () => {
    setSaving(true)
    setMsg('')
    try {
      await api.updateProvider(info.name, {
        label,
        base_url: baseUrl,
        api_key: apiKey || undefined,
        models,
      })
      setMsg(lang === 'zh' ? '已保存' : 'Saved')
      onSaved()
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const handleDiscover = async () => {
    setDiscovering(true)
    setMsg('')
    try {
      const res = await api.discoverModels(info.name)
      setModels(res.models)
      setMsg(lang === 'zh' ? `发现 ${res.models.length} 个模型` : `Discovered ${res.models.length} models`)
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setDiscovering(false)
    }
  }

  const handleAddModel = async () => {
    if (!newModel.trim()) return
    try {
      await api.addProviderModel(info.name, newModel.trim())
      const res = await api.fetchProviders()
      setModels(res.providers.find(p => p.name === info.name)?.models || models)
      setNewModel('')
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  const handleDelete = async () => {
    if (!window.confirm(`删除提供方 ${info.name}？`)) return
    try {
      await api.deleteProvider(info.name)
      onDeleted()
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  return (
    <div className="px-3 pb-3 pt-1 space-y-2 bg-[var(--surface2)]/30">
      {/* API 密钥 */}
      <label className="block text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide">
        {lang === 'zh' ? 'API 密钥' : 'API Key'}
      </label>
      <input
        type="password"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        placeholder={info.has_key ? (lang === 'zh' ? '已配置，输入以替换（留空保留）' : 'Configured — type to replace') : (lang === 'zh' ? '输入 API 密钥，或留空使用环境认证' : 'Enter API key, or leave empty for env auth')}
        className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-2.5 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)] font-mono placeholder:text-[var(--text3)]"
      />

      {/* 自定义设置 */}
      <label className="block text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide pt-1">
        {lang === 'zh' ? '自定义设置' : 'Custom settings'}
      </label>
      <div className="space-y-1.5">
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={lang === 'zh' ? '显示名称' : 'Display name'}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-2.5 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)]"
        />
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={lang === 'zh' ? 'API 地址' : 'API base URL'}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-2.5 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)] font-mono"
        />
      </div>

      {/* 模型目录 */}
      <label className="block text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide pt-1">
        {lang === 'zh' ? '模型目录' : 'Model catalog'}
      </label>
      <div className="flex flex-wrap gap-1">
        {models.map((m) => (
          <span key={m} className="px-1.5 py-0.5 rounded bg-[var(--surface2)] text-[10px] text-[var(--text2)] font-mono">
            {m}
          </span>
        ))}
        {models.length === 0 && (
          <span className="text-[10px] text-[var(--text3)]">
            {lang === 'zh' ? '模型选择器中将不显示任何模型；目录外 ID 仍可直接发送。' : 'No models; out-of-catalog IDs still work.'}
          </span>
        )}
      </div>
      <div className="flex gap-1.5">
        <button
          onClick={handleDiscover}
          disabled={discovering}
          className="flex-1 py-1.5 rounded-md bg-[var(--surface2)] border border-[var(--border)] text-[11px] text-[var(--text2)] hover:text-[var(--text)] hover:border-[var(--accent)] transition-colors disabled:opacity-50"
        >
          {discovering ? '...' : lang === 'zh' ? '获取可用模型' : 'Get models'}
        </button>
        <input
          value={newModel}
          onChange={(e) => setNewModel(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleAddModel() }}
          placeholder={lang === 'zh' ? '添加模型' : 'Add model'}
          className="flex-1 bg-[var(--bg)] border border-[var(--border)] rounded-md px-2.5 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)] font-mono placeholder:text-[var(--text3)]"
        />
        <button
          onClick={handleAddModel}
          className="px-2.5 py-1.5 rounded-md bg-[var(--surface2)] border border-[var(--border)] text-[11px] text-[var(--text2)] hover:text-[var(--text)]"
        >
          +
        </button>
      </div>

      {/* 操作按钮 */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex-1 py-1.5 rounded-md bg-[var(--accent)] text-white text-[11px] font-medium hover:opacity-90 disabled:opacity-50"
        >
          {saving ? '...' : lang === 'zh' ? '保存' : 'Save'}
        </button>
        {info.is_custom && (
          <button
            onClick={handleDelete}
            className="px-3 py-1.5 rounded-md bg-red-500/10 text-red-500 text-[11px] hover:bg-red-500/20"
          >
            {lang === 'zh' ? '删除' : 'Delete'}
          </button>
        )}
      </div>
      {msg && <p className="text-[10px] text-[var(--text2)]">{msg}</p>}
    </div>
  )
}

// ── 添加自定义提供方表单 ──────────────────────────────

function ProviderCreateForm({ lang, onCreated, onCancel }: {
  lang: Language; onCreated: (name: string) => void; onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [label, setLabel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [protocol, setProtocol] = useState('openai-completions')
  const [apiKey, setApiKey] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [newModel, setNewModel] = useState('')
  const [saving, setSaving] = useState(false)
  const [discovering, setDiscovering] = useState(false)
  const [msg, setMsg] = useState('')

  const handleDiscover = async () => {
    setDiscovering(true)
    setMsg('')
    try {
      // 先保存（需要 base_url + key 才能发现），发现后刷新
      await api.createProvider({ name, label, base_url: baseUrl, protocol, api_key: apiKey })
      const res = await api.discoverModels(name)
      setModels(res.models)
      setMsg(lang === 'zh' ? `发现 ${res.models.length} 个模型` : `Discovered ${res.models.length} models`)
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setDiscovering(false)
    }
  }

  const handleAddModel = () => {
    if (!newModel.trim()) return
    if (!models.includes(newModel.trim())) setModels([...models, newModel.trim()])
    setNewModel('')
  }

  const handleCreate = async () => {
    setSaving(true)
    setMsg('')
    try {
      await api.createProvider({ name, label, base_url: baseUrl, protocol, api_key: apiKey, models })
      onCreated(name)
    } catch (e) {
      setMsg((e as Error).message)
      setSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-[var(--border)] p-3 space-y-2 bg-[var(--surface2)]/30">
      <div className="text-[11px] font-semibold text-[var(--text)]">
        {lang === 'zh' ? '自定义提供方' : 'Custom provider'}
      </div>

      {/* Provider ID */}
      <div>
        <label className="block text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide mb-0.5">
          {lang === 'zh' ? 'Provider ID' : 'Provider ID'}
        </label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
          placeholder="acme-gateway"
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-2.5 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)] font-mono"
        />
        <p className="mt-0.5 text-[9px] text-[var(--text3)]">
          {lang === 'zh' ? '以小写字母开头的标识，在请求中唯一标识该提供方，并用于派生凭据名。' : 'Lowercase identifier, unique per provider, derives credential name.'}
        </p>
      </div>

      {/* 显示名称 */}
      <div>
        <label className="block text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide mb-0.5">
          {lang === 'zh' ? '显示名称' : 'Display name'}
        </label>
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={lang === 'zh' ? '显示名称' : 'Display name'}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-2.5 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)]"
        />
      </div>

      {/* API 地址 */}
      <div>
        <label className="block text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide mb-0.5">
          {lang === 'zh' ? 'API 地址' : 'API base URL'}
        </label>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://gateway.example/v1"
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-2.5 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)] font-mono"
        />
      </div>

      {/* 协议 */}
      <div>
        <label className="block text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide mb-0.5">
          {lang === 'zh' ? 'API 协议' : 'API protocol'}
        </label>
        <select
          value={protocol}
          onChange={(e) => setProtocol(e.target.value)}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-2.5 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)] font-mono"
        >
          <option value="openai-completions">openai-completions</option>
          <option value="anthropic-messages">anthropic-messages</option>
          <option value="google-gemini">google-gemini</option>
        </select>
      </div>

      {/* API 密钥 */}
      <div>
        <label className="block text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide mb-0.5">
          {lang === 'zh' ? 'API 密钥' : 'API key'}
        </label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={lang === 'zh' ? '输入 API 密钥' : 'Enter API key'}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-md px-2.5 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)] font-mono"
        />
      </div>

      {/* 模型目录 */}
      <div>
        <label className="block text-[10px] font-semibold text-[var(--text3)] uppercase tracking-wide mb-0.5">
          {lang === 'zh' ? '模型目录' : 'Model catalog'}
        </label>
        <div className="flex gap-1.5 mb-1.5">
          <button
            onClick={handleDiscover}
            disabled={discovering || !name || !baseUrl}
            className="flex-1 py-1.5 rounded-md bg-[var(--surface2)] border border-[var(--border)] text-[11px] text-[var(--text2)] hover:text-[var(--text)] hover:border-[var(--accent)] transition-colors disabled:opacity-40"
          >
            {discovering ? '...' : lang === 'zh' ? '获取可用模型' : 'Get models'}
          </button>
          <input
            value={newModel}
            onChange={(e) => setNewModel(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleAddModel() }}
            placeholder={lang === 'zh' ? '添加模型' : 'Add model'}
            className="flex-1 bg-[var(--bg)] border border-[var(--border)] rounded-md px-2.5 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)] font-mono placeholder:text-[var(--text3)]"
          />
          <button
            onClick={handleAddModel}
            className="px-2.5 rounded-md bg-[var(--surface2)] border border-[var(--border)] text-[11px] text-[var(--text2)] hover:text-[var(--text)]"
          >
            +
          </button>
        </div>
        <div className="flex flex-wrap gap-1">
          {models.map((m) => (
            <span key={m} className="px-1.5 py-0.5 rounded bg-[var(--surface2)] text-[10px] text-[var(--text2)] font-mono">{m}</span>
          ))}
          {models.length === 0 && (
            <span className="text-[10px] text-[var(--text3)]">
              {lang === 'zh' ? '模型选择器中将不显示任何模型；目录外 ID 仍可直接发送。' : 'No models; out-of-catalog IDs still work.'}
            </span>
          )}
        </div>
      </div>

      {msg && <p className="text-[10px] text-[var(--text2)]">{msg}</p>}

      {/* 操作 */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={onCancel}
          className="flex-1 py-1.5 rounded-md bg-[var(--surface2)] border border-[var(--border)] text-[11px] text-[var(--text2)] hover:text-[var(--text)]"
        >
          {lang === 'zh' ? '取消' : 'Cancel'}
        </button>
        <button
          onClick={handleCreate}
          disabled={saving || !name || !baseUrl}
          className="flex-1 py-1.5 rounded-md bg-[var(--accent)] text-white text-[11px] font-medium hover:opacity-90 disabled:opacity-40"
        >
          {saving ? '...' : lang === 'zh' ? '创建提供方' : 'Create provider'}
        </button>
      </div>
    </div>
  )
}

function ThemeSection() {
  const theme = useSettingsStore((s) => s.theme)
  const setTheme = useSettingsStore((s) => s.setTheme)
  const lang = useSettingsStore((s) => s.language)

  const options: { id: Theme; label: { zh: string; en: string }; icon: string }[] = [
    { id: 'dark', label: { zh: '暗色', en: 'Dark' }, icon: '🌙' },
    { id: 'light', label: { zh: '亮色', en: 'Light' }, icon: '☀️' },
    { id: 'system', label: { zh: '跟随系统', en: 'System' }, icon: '🖥️' },
  ]

  return (
    <Section label="Theme">
      <div className="flex gap-2">
        {options.map((opt) => (
          <button
            key={opt.id}
            onClick={() => setTheme(opt.id)}
            className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-all ${
              theme === opt.id
                ? 'bg-[var(--accent)] text-white'
                : 'bg-[var(--surface2)] text-[var(--text2)] hover:text-[var(--text)] border border-[var(--border)]'
            }`}
          >
            <span className="mr-1">{opt.icon}</span>
            {opt.label[lang === 'zh' ? 'zh' : 'en']}
          </button>
        ))}
      </div>
    </Section>
  )
}

function LanguageSection() {
  const lang = useSettingsStore((s) => s.language)
  const setLang = useSettingsStore((s) => s.setLanguage)

  return (
    <Section label="Language / 语言">
      <div className="flex gap-2">
        <button
          onClick={() => setLang('zh')}
          className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all ${
            lang === 'zh'
              ? 'bg-[var(--accent)] text-white'
              : 'bg-[var(--surface2)] text-[var(--text2)] hover:text-[var(--text)] border border-[var(--border)]'
          }`}
        >
          中文
        </button>
        <button
          onClick={() => setLang('en')}
          className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all ${
            lang === 'en'
              ? 'bg-[var(--accent)] text-white'
              : 'bg-[var(--surface2)] text-[var(--text2)] hover:text-[var(--text)] border border-[var(--border)]'
          }`}
        >
          English
        </button>
      </div>
    </Section>
  )
}

function WorkspaceSection() {
  const cwd = useWorkspaceStore((s) => s.cwd)
  const switchWorkspace = useWorkspaceStore((s) => s.switchWorkspace)

  const handleBrowse = async () => {
    try {
      const folder = await window.electronAPI.selectFolder()
      if (folder) {
        await switchWorkspace(folder)
      }
    } catch {
      // Dialog cancelled or error
    }
  }

  return (
    <Section label="Workspace">
      <div className="text-sm font-mono text-[var(--text2)] truncate mb-2">{cwd || 'Not set'}</div>
      <button
        onClick={handleBrowse}
        className="flex items-center gap-2 px-3 py-2 bg-[var(--surface2)] border border-[var(--border)] rounded-lg text-sm text-[var(--text2)] hover:text-[var(--text)] hover:border-[var(--accent)] transition-colors"
      >
        <FolderOpen size={14} /> Browse Folder...
      </button>
    </Section>
  )
}

function FeishuSection() {
  const configured = useSettingsStore((s) => s.feishuConfigured)
  const appId = useSettingsStore((s) => s.feishuAppId)
  const [editAppId, setEditAppId] = useState('')
  const [editSecret, setEditSecret] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  const handleSave = async () => {
    if (!editAppId.trim() || !editSecret.trim()) {
      setMsg('App ID 和 App Secret 不能为空')
      return
    }
    setSaving(true)
    setMsg('')
    try {
      const res = await fetch(`${SERVER_URL}/api/feishu/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_id: editAppId.trim(), app_secret: editSecret.trim() }),
      })
      const data = await res.json()
      if (res.ok) {
        setMsg('已保存！重启后端后生效。')
      } else {
        setMsg(data.error || '保存失败')
      }
    } catch {
      setMsg('网络错误')
    }
    setSaving(false)
  }

  return (
    <Section label="Feishu / 飞书">
      {configured ? (
        <div className="mb-2 text-sm">
          <span className="text-[var(--green)] font-medium">● Connected</span>
          <span className="text-[var(--text2)] ml-2 text-xs font-mono">{appId}</span>
        </div>
      ) : (
        <div className="mb-2">
          <span className="text-[var(--yellow)] text-sm">○ Not configured</span>
        </div>
      )}
      <div className="space-y-2">
        <input
          type="text"
          value={editAppId}
          onChange={(e) => setEditAppId(e.target.value)}
          placeholder="FEISHU_APP_ID (cli_xxx...)"
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)] font-mono placeholder:text-[var(--text3)]"
        />
        <input
          type="password"
          value={editSecret}
          onChange={(e) => setEditSecret(e.target.value)}
          placeholder="FEISHU_APP_SECRET"
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)] font-mono placeholder:text-[var(--text3)]"
        />
        <button
          onClick={handleSave}
          disabled={saving}
          className="w-full py-2 bg-[var(--accent)] text-white rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
        {msg && (
          <p className={`text-[11px] ${msg.includes('成功') || msg.includes('保存') ? 'text-[var(--green)]' : 'text-[var(--red)]'}`}>
            {msg}
          </p>
        )}
      </div>
    </Section>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[10px] font-bold uppercase tracking-wider text-[var(--text3)] mb-2">
        {label}
      </label>
      {children}
    </div>
  )
}
