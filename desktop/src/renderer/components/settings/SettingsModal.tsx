import { useState } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import { useUIStore } from '@/stores/uiStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { Modal } from '@/components/common/Modal'
import type { Theme, Language } from '@/types'
import { FolderOpen } from 'lucide-react'
import { SERVER_URL } from '@/lib/constants'

export function SettingsModal() {
  const open = useUIStore((s) => s.isSettingsOpen)
  const close = useUIStore((s) => s.closeSettings)
  const currentLang = useSettingsStore((s) => s.language)

  const t = (zh: string, en: string) => (currentLang === 'zh' ? zh : en)

  return (
    <Modal open={open} onClose={close} title={t('设置', 'Settings')} maxWidth="max-w-md">
      <div className="space-y-6">
        <ThemeSection />
        <LanguageSection />
        <WorkspaceSection />
        <FeishuSection />
      </div>
    </Modal>
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
