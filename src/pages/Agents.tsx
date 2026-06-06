import { useState, useEffect, useCallback } from 'react';

import { Button } from '../components/common';
import { agentsApi, type AgentProfile } from '../lib/api';
import { AgentCard, AgentDetails, EditAgentForm } from '../widgets/agents';

export function Agents() {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<AgentProfile | null>(null);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<Partial<AgentProfile>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await agentsApi.list();
      setAgents(data);
    } catch (err) {
      setError(`加载失败: ${err instanceof Error ? err.message : '未知错误'}`);
      setAgents(getMockAgents());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  const handleToggleAgent = async (agentId: string, enabled: boolean) => {
    setAgents((prev) => prev.map((a) => (a.id === agentId ? { ...a, enabled } : a)));
    try {
      await agentsApi.toggle(agentId, enabled);
    } catch {
      setAgents((prev) => prev.map((a) => (a.id === agentId ? { ...a, enabled: !enabled } : a)));
      setError('切换失败');
    }
  };

  const handleSave = async () => {
    if (!selectedAgent) return;
    try {
      const updated = { ...selectedAgent, ...editForm } as AgentProfile;
      await agentsApi.update(updated);
      setEditing(false);
      setEditForm({});
      loadAgents();
    } catch {
      setError('保存失败');
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Agent 管理</h1>
          <Button variant="primary" onClick={loadAgents}>
            刷新
          </Button>
        </div>

        {error && <div className="mb-4 p-3 rounded-lg bg-error/10 text-error text-sm">{error}</div>}

        {loading ? (
          <div className="flex items-center justify-center py-12 text-muted">加载中...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                isSelected={selectedAgent?.id === agent.id}
                onSelect={() => {
                  setSelectedAgent(agent);
                  setEditing(false);
                  setEditForm({});
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
                  setEditing(false);
                  setEditForm({});
                }}
              />
            ) : (
              <AgentDetails agent={selectedAgent} />
            )}
          </div>
        )}
      </div>
    </div>
  );
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
  ];
}
