import { useState, useEffect, useCallback } from 'react'

import { Button } from '../components/common'
import { agentsApi, type AgentProfile } from '../lib/api'

const ROLE_LABELS: Record<string, string> = {
  coordinator: '协调器',
  researcher: '研究员',
  coder: '工程师',
  memory_manager: '记忆管理',
}

const ROLE_COLORS: Record<string, string> = {
  coordinator: 'bg-role-blue text-role-blue-text',
  researcher: 'bg-role-green text-role-green-text',
  coder: 'bg-role-purple text-role-purple-text',
  memory_manager: 'bg-role-orange text-role-orange-text',
}

export function Agents() {
  const [agents, setAgents] = useState<AgentProfile[]>([])
  const [selectedAgent, setSelectedAgent] = useState<AgentProfile | null>(null)
  const [editing, setEditing] = useState(false)
  const [editForm, setEditForm] = useState<Partial<AgentProfile>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadAgents = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await agentsApi.list()
      setAgents(data)
    } catch (err) {
      setError(`加载失败: ${err instanceof Error ? err.message : '未知错误'}`)
      setAgents(getMockAgents())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAgents()
  }, [loadAgents])

  const handleToggleAgent = async (agentId: string, enabled: boolean) => {
    setAgents((prev) =>
      prev.map((a) => (a.id === agentId ? { ...a, enabled } : a))
    )
    try {
      await agentsApi.toggle(agentId, enabled)
    } catch {
      setAgents((prev) =>
        prev.map((a) => (a.id === agentId ? { ...a, enabled: !enabled } : a))
      )
      setError('切换失败')
    }
  }

  const handleSave = async () => {
    if (!selectedAgent) return
    try {
      const updated = { ...selectedAgent, ...editForm } as AgentProfile
      await agentsApi.update(updated)
      setEditing(false)
      setEditForm({})
      loadAgents()
    } catch {
      setError('保存失败')
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Agent 管理</h1>
          <Button variant="primary" onClick={loadAgents}>
            刷新
          </Button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-error/10 text-error text-sm">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-12 text-muted">
            加载中...
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                isSelected={selectedAgent?.id === agent.id}
                onSelect={() => {
                  setSelectedAgent(agent)
                  setEditing(false)
                  setEditForm({})
                }}
                onToggle={handleToggleAgent}
              />
            ))}
          </div>
        )}

        {selectedAgent && (
          <div className="mt-6 p-6 rounded-lg border border-border bg-surface-elevated dark:bg-surface">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">{selectedAgent.name}</h2>
              {!editing && (
                <Button variant="secondary" onClick={() => setEditing(true)}>
                  编辑
                </Button>
              )}
            </div>

            {editing ? (
              <EditAgentForm
                agent={selectedAgent}
                form={editForm}
                onChange={setEditForm}
                onSave={handleSave}
                onCancel={() => {
                  setEditing(false)
                  setEditForm({})
                }}
              />
            ) : (
              <AgentDetails agent={selectedAgent} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ========== 子组件 ==========

function AgentCard({
  agent,
  isSelected,
  onSelect,
  onToggle,
}: {
  agent: AgentProfile
  isSelected: boolean
  onSelect: () => void
  onToggle: (id: string, enabled: boolean) => void
}) {
  const roleColor = ROLE_COLORS[agent.role] || 'bg-bg-subtle text-text-secondary'
  const roleLabel = ROLE_LABELS[agent.role] || agent.role

  return (
    <div
      onClick={onSelect}
      className={`p-4 rounded-lg border cursor-pointer transition-all ${
        isSelected
          ? 'border-primary bg-primary/10'
          : 'border-border hover:border-border-hover'
      } ${!agent.enabled ? 'opacity-50' : ''}`}
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-medium">{agent.name}</h3>
        <span className={`px-2 py-0.5 text-xs rounded-full ${roleColor}`}>
          {roleLabel}
        </span>
      </div>

      <p className="text-sm text-muted mb-3 line-clamp-2">
        {agent.description}
      </p>

      <div className="flex items-center justify-between">
        <span className="text-xs text-muted">
          模型: {agent.model_config.model}
        </span>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={agent.enabled}
            onChange={(e) => {
              e.stopPropagation()
              onToggle(agent.id, e.target.checked)
            }}
            className="rounded"
          />
          启用
        </label>
      </div>
    </div>
  )
}

function AgentDetails({ agent }: { agent: AgentProfile }) {
  return (
    <div className="space-y-4">
      <div>
        <span className="text-sm font-medium text-muted">ID</span>
        <p className="text-sm font-mono mt-1">{agent.id}</p>
      </div>

      <div>
        <span className="text-sm font-medium text-muted">系统提示</span>
        <pre className="text-sm mt-1 p-3 rounded bg-bg-subtle dark:bg-bg-muted whitespace-pre-wrap">
          {agent.system_prompt}
        </pre>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <span className="text-sm font-medium text-muted">工具</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {agent.tools.map((tool) => (
              <span
                key={tool}
                className="px-2 py-0.5 text-xs rounded bg-bg-subtle"
              >
                {tool}
              </span>
            ))}
          </div>
        </div>

        <div>
          <span className="text-sm font-medium text-muted">记忆访问</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {agent.memory_access.map((mem) => (
              <span
                key={mem}
                className="px-2 py-0.5 text-xs rounded bg-bg-subtle"
              >
                {mem}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <span className="text-sm font-medium text-muted">模型</span>
          <p className="text-sm mt-1">{agent.model_config.model}</p>
        </div>
        <div>
          <span className="text-sm font-medium text-muted">Temperature</span>
          <p className="text-sm mt-1">{agent.model_config.temperature}</p>
        </div>
        <div>
          <span className="text-sm font-medium text-muted">Max Tokens</span>
          <p className="text-sm mt-1">{agent.model_config.max_tokens}</p>
        </div>
      </div>

      <div>
        <span className="text-sm font-medium text-muted">最大迭代次数</span>
        <p className="text-sm mt-1">{agent.max_iterations}</p>
      </div>
    </div>
  )
}

function EditAgentForm({
  agent,
  form,
  onChange,
  onSave,
  onCancel,
}: {
  agent: AgentProfile
  form: Partial<AgentProfile>
  onChange: (form: Partial<AgentProfile>) => void
  onSave: () => void
  onCancel: () => void
}) {
  const value = <K extends keyof AgentProfile>(key: K): AgentProfile[K] =>
    (form[key] !== undefined ? form[key] : agent[key]) as AgentProfile[K]

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium mb-1">名称</label>
        <input
          type="text"
          value={value('name')}
          onChange={(e) => onChange({ ...form, name: e.target.value })}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">描述</label>
        <input
          type="text"
          value={value('description')}
          onChange={(e) => onChange({ ...form, description: e.target.value })}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">系统提示</label>
        <textarea
          value={value('system_prompt')}
          onChange={(e) => onChange({ ...form, system_prompt: e.target.value })}
          rows={4}
          className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
        />
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1">模型</label>
          <input
            type="text"
            value={value('model_config').model}
            onChange={(e) =>
              onChange({
                ...form,
                model_config: { ...value('model_config'), model: e.target.value },
              })
            }
            className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Temperature</label>
          <input
            type="number"
            min="0"
            max="2"
            step="0.1"
            value={value('model_config').temperature}
            onChange={(e) =>
              onChange({
                ...form,
                model_config: {
                  ...value('model_config'),
                  temperature: parseFloat(e.target.value),
                },
              })
            }
            className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Max Tokens</label>
          <input
            type="number"
            min="256"
            max="8192"
            step="256"
            value={value('model_config').max_tokens}
            onChange={(e) =>
              onChange({
                ...form,
                model_config: {
                  ...value('model_config'),
                  max_tokens: parseInt(e.target.value),
                },
              })
            }
            className="w-full rounded-lg border border-border px-3 py-2 bg-surface dark:bg-surface-elevated"
          />
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          取消
        </Button>
        <Button variant="primary" onClick={onSave}>
          保存
        </Button>
      </div>
    </div>
  )
}

function getMockAgents(): AgentProfile[] {
  return [
    {
      id: 'primary',
      name: 'Sage 主助手',
      role: 'coordinator',
      description: '面向用户的协调 Agent，负责意图识别和任务分发',
      system_prompt: '你是 Sage，一个智能 AI 助手。',
      tools: ['calculator', 'memory_search', 'memory_save'],
      memory_access: ['working', 'episodic', 'semantic'],
      model_config: { model: 'gpt-4', temperature: 0.7, max_tokens: 4096 },
      max_iterations: 10,
      enabled: true,
    },
    {
      id: 'researcher',
      name: '研究 Agent',
      role: 'researcher',
      description: '负责网络搜索和信息收集',
      system_prompt: '你是一个专业的研究 Agent。',
      tools: ['web_search', 'web_fetch', 'memory_search'],
      memory_access: ['episodic', 'semantic'],
      model_config: { model: 'gpt-4', temperature: 0.5, max_tokens: 4096 },
      max_iterations: 8,
      enabled: true,
    },
    {
      id: 'coder',
      name: '编码 Agent',
      role: 'coder',
      description: '负责代码生成、调试和审查',
      system_prompt: '你是一个专业的编码 Agent。',
      tools: ['file_read', 'file_write', 'terminal', 'calculator'],
      memory_access: ['semantic'],
      model_config: { model: 'gpt-4', temperature: 0.3, max_tokens: 4096 },
      max_iterations: 15,
      enabled: true,
    },
    {
      id: 'memory_manager',
      name: '记忆 Agent',
      role: 'memory_manager',
      description: '负责记忆管理和知识提取',
      system_prompt: '你是一个记忆管理 Agent。',
      tools: ['memory_search', 'memory_save'],
      memory_access: ['working', 'episodic', 'semantic'],
      model_config: { model: 'gpt-3.5-turbo', temperature: 0.5, max_tokens: 4096 },
      max_iterations: 5,
      enabled: true,
    },
  ]
}
