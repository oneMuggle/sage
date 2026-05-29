import { useState } from 'react'
import { clsx } from 'clsx'
import { EvolutionPanel } from '../components/evolution/EvolutionPanel'
import { EvolutionLog } from '../components/evolution/EvolutionLog'

type SettingsTab = 'general' | 'model' | 'memory' | 'network' | 'evolution'

export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general')
  const [streaming, setStreaming] = useState(true)
  const [autoMemory, setAutoMemory] = useState(true)
  const [confirmDelete, setConfirmDelete] = useState(true)
  const [compactMode, setCompactMode] = useState(false)
  const [model, setModel] = useState('claude-3.5-sonnet')
  const [apiUrl, setApiUrl] = useState('http://api.internal.sage:8080')
  const [maxContext, setMaxContext] = useState('4096')
  const [temperature, setTemperature] = useState('0.7')
  const [proxyMode, setProxyMode] = useState('system')
  const [proxyUrl, setProxyUrl] = useState('http://proxy.internal:3128')
  const [tlsVersion, setTlsVersion] = useState('1.2')

  const tabs: { key: SettingsTab; label: string }[] = [
    { key: 'general', label: '通用' },
    { key: 'model', label: '模型' },
    { key: 'memory', label: '记忆' },
    { key: 'network', label: '网络' },
    { key: 'evolution', label: '进化' },
  ]

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 页面头部 */}
      <div className="h-12 flex items-center px-5 border-b border-border bg-surface flex-shrink-0">
        <h2 className="text-[18px] font-semibold text-text">设置</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        <div className="flex gap-1 border-b border-border mb-5">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={clsx(
                'px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
                activeTab === tab.key
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted hover:text-text',
              )}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === 'general' && (
          <div className="space-y-6">
            <section>
              <h3 className="text-sm font-semibold text-text mb-3">外观</h3>
              <SettingRow label="紧凑模式" desc="减少间距，在同一屏幕内显示更多内容">
                <Toggle value={compactMode} onChange={setCompactMode} />
              </SettingRow>
              <SettingRow label="流式输出" desc="逐字显示 AI 回复，而非等待全部生成完成">
                <Toggle value={streaming} onChange={setStreaming} />
              </SettingRow>
            </section>
            <section>
              <h3 className="text-sm font-semibold text-text mb-3">对话</h3>
              <SettingRow label="自动记忆提取" desc="对话中自动识别并保存关键信息到记忆库">
                <Toggle value={autoMemory} onChange={setAutoMemory} />
              </SettingRow>
              <SettingRow label="确认后再删除记忆" desc="删除记忆前弹出确认对话框">
                <Toggle value={confirmDelete} onChange={setConfirmDelete} />
              </SettingRow>
            </section>
          </div>
        )}

        {activeTab === 'model' && (
          <div className="space-y-6">
            <section>
              <h3 className="text-sm font-semibold text-text mb-3">模型配置</h3>
              <SettingRow label="默认模型" desc="新建对话时使用的 AI 模型">
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
                >
                  <option value="claude-3.5-sonnet">Claude 3.5 Sonnet</option>
                  <option value="claude-3.5-haiku">Claude 3.5 Haiku</option>
                  <option value="claude-3-opus">Claude 3 Opus</option>
                </select>
              </SettingRow>
              <SettingRow label="API 地址" desc="内部 API 网关或代理地址">
                <input
                  type="text"
                  value={apiUrl}
                  onChange={(e) => setApiUrl(e.target.value)}
                  className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
                />
              </SettingRow>
              <SettingRow label="最大上下文长度" desc="单次对话发送给模型的最大 token 数">
                <input
                  type="text"
                  value={maxContext}
                  onChange={(e) => setMaxContext(e.target.value)}
                  className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
                />
              </SettingRow>
              <SettingRow label="Temperature" desc="控制输出的随机性，0 最确定，1 最随机">
                <input
                  type="text"
                  value={temperature}
                  onChange={(e) => setTemperature(e.target.value)}
                  className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
                />
              </SettingRow>
            </section>
          </div>
        )}

        {activeTab === 'memory' && (
          <div className="space-y-6">
            <section>
              <h3 className="text-sm font-semibold text-text mb-3">记忆管理</h3>
              <SettingRow label="本地存储路径" desc="记忆数据在本地文件系统中的存储位置">
                <input
                  type="text"
                  value="%APPDATA%\\Sage\\memory.db"
                  readOnly
                  className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-bg-muted text-text-secondary"
                />
              </SettingRow>
              <SettingRow label="同步到内部服务器" desc="联网时将记忆增量同步到企业内部服务器">
                <Toggle value={autoMemory} onChange={setAutoMemory} />
              </SettingRow>
            </section>
          </div>
        )}

        {activeTab === 'network' && (
          <div className="space-y-6">
            <section>
              <h3 className="text-sm font-semibold text-text mb-3">网络配置</h3>
              <SettingRow label="代理模式" desc="企业内部网络通常需要配置代理">
                <select
                  value={proxyMode}
                  onChange={(e) => setProxyMode(e.target.value)}
                  className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
                >
                  <option value="system">系统代理</option>
                  <option value="custom">自定义代理</option>
                  <option value="direct">直连</option>
                </select>
              </SettingRow>
              <SettingRow label="代理地址" desc="HTTP 代理服务器地址">
                <input
                  type="text"
                  value={proxyUrl}
                  onChange={(e) => setProxyUrl(e.target.value)}
                  className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
                />
              </SettingRow>
              <SettingRow label="TLS 版本" desc="Windows 7 最高支持 TLS 1.2">
                <select
                  value={tlsVersion}
                  onChange={(e) => setTlsVersion(e.target.value)}
                  className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
                >
                  <option value="1.2">TLS 1.2</option>
                  <option value="1.3">TLS 1.3</option>
                </select>
              </SettingRow>
            </section>
          </div>
        )}

        {activeTab === 'evolution' && (
          <div className="space-y-6">
            <EvolutionPanel />
            <EvolutionLog />
          </div>
        )}
      </div>
    </div>
  )
}

/* ---- Sub-components ---- */

interface SettingRowProps {
  label: string
  desc: string
  children: React.ReactNode
}

function SettingRow({ label, desc, children }: SettingRowProps) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-border">
      <div>
        <div className="text-sm text-text">{label}</div>
        <div className="text-xs text-muted mt-0.5">{desc}</div>
      </div>
      <div>{children}</div>
    </div>
  )
}

interface ToggleProps {
  value: boolean
  onChange: (v: boolean) => void
}

function Toggle({ value, onChange }: ToggleProps) {
  return (
    <button
      className={`w-9 h-5 rounded-full relative transition-colors ${
        value ? 'bg-primary' : 'bg-border'
      }`}
      onClick={() => onChange(!value)}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-text-inverse transition-transform ${
          value ? 'translate-x-4' : ''
        }`}
      />
    </button>
  )
}
