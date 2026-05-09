import { useState } from 'react'
import { Button } from '../components/common'

export function Settings() {
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

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-2xl font-bold mb-6">设置</h1>

        {/* 模型设置 */}
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

        {/* 界面设置 */}
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

        {/* 保存按钮 */}
        <div className="flex justify-end">
          <Button variant="primary" onClick={handleSave}>
            保存设置
          </Button>
        </div>
      </div>
    </div>
  )
}
