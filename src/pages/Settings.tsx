import { useState } from 'react'
import { Button } from '../components/common'
import { EvolutionPanel } from '../components/evolution/EvolutionPanel'
import { EvolutionLog } from '../components/evolution/EvolutionLog'

type SettingsTab = 'general' | 'model' | 'interface' | 'evolution'

export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general')
  const [settings, setSettings] = useState({
    model: 'gpt-3.5-turbo',
    temperature: 0.7,
    maxTokens: 4096,
    theme: 'light',
    language: 'zh-CN',
  })

  const handleSave = () => {
    // 保存设置到后端
    console.log('保存设置:', settings)
  }

  const tabs: { key: SettingsTab; label: string }[] = [
    { key: 'general', label: '通用' },
    { key: 'model', label: '模型' },
    { key: 'interface', label: '界面' },
    { key: 'evolution', label: '进化' },
  ]

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-2xl font-bold mb-6">设置</h1>

        {/* 标签导航 */}
        <div className="flex border-b border-gray-200 mb-6">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* 通用设置 */}
        {activeTab === 'general' && (
          <section className="space-y-4">
            <p className="text-gray-500">通用设置内容</p>
          </section>
        )}

        {/* 模型设置 */}
        {activeTab === 'model' && (
          <section className="mb-8">
            <h2 className="text-lg font-semibold mb-4">模型设置</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">默认模型</label>
                <select
                  value={settings.model}
                  onChange={(e) => setSettings({ ...settings, model: e.target.value })}
                  className="w-full rounded-lg border border-gray-200 dark:border-gray-600 px-3 py-2 bg-white dark:bg-gray-700"
                >
                  <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
                  <option value="gpt-4">GPT-4</option>
                  <option value="claude-3">Claude 3</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">
                  Temperature: {settings.temperature}
                </label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={settings.temperature}
                  onChange={(e) => setSettings({ ...settings, temperature: parseFloat(e.target.value) })}
                  className="w-full"
                />
                <p className="text-xs text-gray-500 mt-1">较低的值更确定性，较高的值更有创造性</p>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">
                  最大 Token 数: {settings.maxTokens}
                </label>
                <input
                  type="range"
                  min="512"
                  max="8192"
                  step="256"
                  value={settings.maxTokens}
                  onChange={(e) => setSettings({ ...settings, maxTokens: parseInt(e.target.value) })}
                  className="w-full"
                />
              </div>
            </div>
          </section>
        )}

        {/* 界面设置 */}
        {activeTab === 'interface' && (
          <section className="mb-8">
            <h2 className="text-lg font-semibold mb-4">界面设置</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">主题</label>
                <select
                  value={settings.theme}
                  onChange={(e) => setSettings({ ...settings, theme: e.target.value })}
                  className="w-full rounded-lg border border-gray-200 dark:border-gray-600 px-3 py-2 bg-white dark:bg-gray-700"
                >
                  <option value="light">浅色</option>
                  <option value="dark">深色</option>
                  <option value="auto">跟随系统</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">语言</label>
                <select
                  value={settings.language}
                  onChange={(e) => setSettings({ ...settings, language: e.target.value })}
                  className="w-full rounded-lg border border-gray-200 dark:border-gray-600 px-3 py-2 bg-white dark:bg-gray-700"
                >
                  <option value="zh-CN">简体中文</option>
                  <option value="en">English</option>
                </select>
              </div>
            </div>
          </section>
        )}

        {/* 进化设置 */}
        {activeTab === 'evolution' && (
          <section className="mb-8">
            <EvolutionPanel />
            
            <div className="mt-8">
              <EvolutionLog />
            </div>
          </section>
        )}

        {/* 保存按钮（仅非进化标签页显示） */}
        {activeTab !== 'evolution' && (
          <div className="flex justify-end">
            <Button variant="primary" onClick={handleSave}>
              保存设置
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
