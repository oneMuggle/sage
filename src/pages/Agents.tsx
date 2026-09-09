import { useState, useEffect, useCallback } from 'react';

import { agentsApi, type AgentProfile, type AgentUpdate } from '../shared/api';
import { Button } from '../shared/ui';
import { ErrorState } from '../shared/ui/ErrorState';
import { LoadingState } from '../shared/ui/LoadingState';
import { RetryButton } from '../shared/ui/RetryButton';
import { AgentCard, AgentDetails, EditAgentForm } from '../widgets/agents';

export function Agents() {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<AgentProfile | null>(null);
  const [editing, setEditing] = useState(false);
  // 用 Partial<AgentUpdate> 而非 Partial<AgentProfile> — 避免 id/updated_at
  // 等不允许更新的字段悄悄随 PATCH body 一起送出 (Pydantic 不会接, 但
  // 类型层面应当先拦)。EditAgentForm 实际只动 name/description/system_prompt/model_config。
  const [editForm, setEditForm] = useState<Partial<AgentUpdate>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await agentsApi.list();
      setAgents(data);
    } catch (err) {
      // U2 (P5): 失败不再回退渲染 mock agent —— 假数据会误导用户;
      // 保留 error 态由页面错误分支呈现。
      setError(`加载失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  const handleToggleAgent = async (agentId: string, enabled: boolean) => {
    // Optimistic update: 先反应 UI, 失败再回滚
    setAgents((prev) => prev.map((a) => (a.id === agentId ? { ...a, enabled } : a)));
    try {
      // PR-5: toggle 返回完整 profile, 用返回值覆盖本地状态 (含新 updated_at)
      const updated = await agentsApi.toggle(agentId, enabled);
      setAgents((prev) => prev.map((a) => (a.id === agentId ? updated : a)));
      if (selectedAgent?.id === agentId) {
        setSelectedAgent(updated);
      }
    } catch {
      setAgents((prev) => prev.map((a) => (a.id === agentId ? { ...a, enabled: !enabled } : a)));
      setError('切换失败');
    }
  };

  const handleSave = async () => {
    if (!selectedAgent) return;
    try {
      // PR-4 契约: 仅传 diff (editForm 已是 Partial<AgentUpdate>, 无需 cast)
      const updated = await agentsApi.update(selectedAgent.id, editForm);
      // 用后端返回的完整 profile 覆盖本地状态 (避免漂移)
      setAgents((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
      setSelectedAgent(updated);
      setEditing(false);
      setEditForm({});
    } catch {
      setError('保存失败');
    }
  };

  // 首次加载且失败 + 尚无数据：整页 ErrorState + 重试
  if (loading && agents.length === 0 && error) {
    return (
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-2xl font-bold">Agent 管理</h1>
            <Button variant="primary" onClick={loadAgents}>
              刷新
            </Button>
          </div>
          <ErrorState
            title="Agent 列表加载失败"
            message={error}
            onRetry={loadAgents}
            retryLabel="重新加载"
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Agent 管理</h1>
          <div className="flex items-center gap-2">
            <Button variant="primary" onClick={loadAgents}>
              刷新
            </Button>
            {error && (
              <RetryButton onRetry={loadAgents} label="重试" className="!px-3 !py-1.5 !text-xs" />
            )}
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-error/10 text-error text-sm flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="text-error hover:underline">
              关闭
            </button>
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <LoadingState label="加载 Agent 中..." />
          </div>
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

