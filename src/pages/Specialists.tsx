import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import {
  agentsApi,
  sessionApi,
  specialistApi,
  type AgentProfile,
} from '../shared/api';
import { useStore } from '../shared/lib/store';
import { Button, PageHeader } from '../shared/ui';
import { ErrorState } from '../shared/ui/ErrorState';
import { LoadingState } from '../shared/ui/LoadingState';
import { SpecialistCard } from '../widgets/specialists/SpecialistCard';
import { SpecialistWizard } from '../widgets/specialists/SpecialistWizard';

/**
 * /specialists 画廊页（M1-E）。
 *
 * 展示所有 role=specialist 的 AgentProfile，提供「新建专家」「导入专家包」
 * 入口；点击卡片「试聊」会创建会话、绑定该专家并跳转到 /chat；
 * 「编辑」「导出」通过 SpecialistCard 回调触发。
 *
 * 筛选策略：同时列出 builtin/user/imported 三种来源，但画廊卡片样式统一
 * 以 SpecialistCard 渲染；未来若需区分「我的专家/公共专家」再加分组。
 */
export function Specialists() {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportingId, setExportingId] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentProfile | null>(null);
  const navigate = useNavigate();

  const loadAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await agentsApi.list();
      setAgents(data.filter((a) => a.role === 'specialist'));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  async function handleImport() {
    if (!specialistApi.isAvailable()) {
      toast.error('专家包导入/导出仅在桌面端可用');
      return;
    }
    try {
      const result = await specialistApi.importPackage();
      if (!result) return;
      toast.success(`已导入专家 ${result.name}（${result.id}）`);
      await loadAgents();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`导入失败：${message}`);
    }
  }

  async function handleExport(agent: AgentProfile) {
    if (!specialistApi.isAvailable()) {
      toast.error('专家包导入/导出仅在桌面端可用');
      return;
    }
    setExportingId(agent.id);
    try {
      const result = await specialistApi.exportPackage(agent.id);
      if (result) toast.success(`已导出到 ${result.path}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`导出失败：${message}`);
    } finally {
      setExportingId(null);
    }
  }

  function handleEdit(agent: AgentProfile) {
    setEditingAgent(agent);
    setWizardOpen(true);
  }

  function handleOpenCreate() {
    setEditingAgent(null);
    setWizardOpen(true);
  }

  async function handleStartChat(agent: AgentProfile) {
    try {
      const sid = await useStore.getState().createSession();
      await sessionApi.setSpecialist(sid, agent.id);
      useStore.getState().updateSession(sid, { specialist_id: agent.id });
      navigate('/chat');
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`进入试聊失败：${message}`);
    }
  }

  if (loading && agents.length === 0) {
    return (
      <div className="flex-1 overflow-auto">
        <LoadingState label="加载专家列表…" />
      </div>
    );
  }

  if (error && agents.length === 0) {
    return (
      <div className="flex-1 overflow-auto">
        <ErrorState message={error} onRetry={loadAgents} />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto">
      <PageHeader
        title="专家"
        subtitle="生产力型专家，每个专家拥有独立的人设、技能与权限。"
        actions={
          <div className="flex items-center gap-2">
            {specialistApi.isAvailable() && (
              <Button variant="secondary" size="sm" onClick={handleImport}>
                导入专家包
              </Button>
            )}
            <Button size="sm" onClick={handleOpenCreate}>
              新建专家
            </Button>
          </div>
        }
      />

      <div className="mx-auto max-w-7xl px-6 py-6">
        {agents.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-bg-subtle/40 p-8 text-center">
            <p className="text-sm text-muted">还没有专家，点击「新建专家」创建第一位。</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent) => (
              <SpecialistCard
                key={agent.id}
                agent={agent}
                onChat={handleStartChat}
                onEdit={handleEdit}
                onExport={handleExport}
                exporting={exportingId === agent.id}
              />
            ))}
          </div>
        )}
      </div>

      <SpecialistWizard
        open={wizardOpen}
        onOpenChange={(open) => {
          setWizardOpen(open);
          if (!open) setEditingAgent(null);
        }}
        editingAgent={editingAgent ?? undefined}
        onSaved={loadAgents}
      />
    </div>
  );
}
