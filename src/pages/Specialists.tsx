import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { agentsApi, sessionApi, specialistApi, type AgentProfile } from '../shared/api';
import { useStore } from '../shared/lib/store';
import { Button, PageHeader } from '../shared/ui';
import { ErrorState } from '../shared/ui/ErrorState';
import { LoadingState } from '../shared/ui/LoadingState';
import { GroupChatDialog } from '../widgets/specialists/GroupChatDialog';
import { KnowledgeBindingsEditor } from '../widgets/specialists/KnowledgeBindingsEditor';
import { SpecialistAssetsDialog } from '../widgets/specialists/SpecialistAssetsDialog';
import { SpecialistCard } from '../widgets/specialists/SpecialistCard';
import { SpecialistEvalDialog } from '../widgets/specialists/SpecialistEvalDialog';
import { SpecialistWizard } from '../widgets/specialists/SpecialistWizard';
import { TemplateGalleryDialog } from '../widgets/specialists/TemplateGalleryDialog';
import { VersionHistoryDialog } from '../widgets/specialists/VersionHistoryDialog';

type SourceFilter = 'all' | 'builtin' | 'user' | 'imported';

const SOURCE_FILTERS: ReadonlyArray<{ key: SourceFilter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'builtin', label: '内置' },
  { key: 'user', label: '我的' },
  { key: 'imported', label: '导入' },
];

/** 与后端 legacy_agent_routes.PROTECTED_AGENT_IDS 一致：产品入口专家不可删除。 */
const PROTECTED_AGENT_IDS = new Set(['primary', 'sage-guide']);

/** 搜索匹配文本：名称 + 标语（persona_ui.tagline）+ 描述。 */
function specialistSearchText(agent: AgentProfile): string {
  const ui = agent.persona_ui as Record<string, unknown> | undefined;
  const tagline = typeof ui?.tagline === 'string' ? ui.tagline : '';
  return `${agent.name ?? ''} ${tagline} ${agent.description ?? ''}`.toLowerCase();
}

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
  const [knowledgeAgent, setKnowledgeAgent] = useState<AgentProfile | null>(null);
  const [assetsAgent, setAssetsAgent] = useState<AgentProfile | null>(null);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [groupChatOpen, setGroupChatOpen] = useState(false);
  const [versionsAgent, setVersionsAgent] = useState<AgentProfile | null>(null);
  const [evalAgent, setEvalAgent] = useState<AgentProfile | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  // P2-a: 批量操作选择模式
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
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

  const filteredAgents = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return agents
      .filter((agent) => {
        if (sourceFilter !== 'all' && (agent.source ?? 'user') !== sourceFilter) return false;
        if (!query) return true;
        return specialistSearchText(agent).includes(query);
      })
      .sort((a, b) => {
        const orderDiff = (a.sort_order ?? 0) - (b.sort_order ?? 0);
        if (orderDiff !== 0) return orderDiff;
        return a.name.localeCompare(b.name, 'zh-Hans');
      });
  }, [agents, sourceFilter, searchQuery]);

  const hasActiveFilters = sourceFilter !== 'all' || searchQuery.trim() !== '';

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

  function handleKnowledge(agent: AgentProfile) {
    setKnowledgeAgent(agent);
  }

  function handleAssets(agent: AgentProfile) {
    setAssetsAgent(agent);
  }

  function handleVersions(agent: AgentProfile) {
    setVersionsAgent(agent);
  }

  function handleEval(agent: AgentProfile) {
    setEvalAgent(agent);
  }

  // P2-a: 批量操作
  function toggleSelectionMode() {
    setSelectionMode((prev) => {
      if (prev) setSelectedIds(new Set());
      return !prev;
    });
  }

  function toggleSelect(agentId: string) {
    if (PROTECTED_AGENT_IDS.has(agentId)) return;
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      return next;
    });
  }

  async function handleBatch(action: 'delete' | 'enable' | 'disable') {
    if (selectedIds.size === 0) return;
    if (action === 'delete') {
      const confirmed = window.confirm(
        `确定删除选中的 ${selectedIds.size} 位专家？此操作不可撤销。`,
      );
      if (!confirmed) return;
    }
    setBatchBusy(true);
    try {
      const result = await agentsApi.batch(action, Array.from(selectedIds));
      const labels = { delete: '删除', enable: '启用', disable: '禁用' } as const;
      if (result.failed.length === 0) {
        toast.success(`已${labels[action]} ${result.succeeded.length} 位专家`);
      } else {
        toast.warning(
          `已${labels[action]} ${result.succeeded.length} 位，${result.failed.length} 位失败`,
        );
      }
      setSelectedIds(new Set());
      setSelectionMode(false);
      await loadAgents();
    } catch (err) {
      toast.error(`批量操作失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBatchBusy(false);
    }
  }

  // P2-d: 置顶（整序列重排后一次性提交）
  async function handlePin(agent: AgentProfile) {
    const orderedIds = [
      agent.id,
      ...filteredAgents.map((a) => a.id).filter((id) => id !== agent.id),
    ];
    try {
      await agentsApi.reorder(orderedIds.map((id, index) => ({ id, sort_order: index })));
      toast.success(`已将「${agent.name}」置顶`);
      await loadAgents();
    } catch (err) {
      toast.error(`置顶失败：${err instanceof Error ? err.message : String(err)}`);
    }
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
            <Button variant="secondary" size="sm" onClick={() => setGroupChatOpen(true)}>
              新建群聊
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setTemplateOpen(true)}>
              从模板创建
            </Button>
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
          <div className="rounded-xl border border-dashed border-border bg-bg-subtle/40 p-10 text-center">
            <div className="text-4xl" aria-hidden="true">
              🎨
            </div>
            <p className="mt-3 text-base font-medium">还没有专家</p>
            <p className="mt-1 text-sm text-muted">
              创建一个专家，让它帮你完成专业任务；也可以从模板一键开始。
            </p>
            <div className="mt-4 flex items-center justify-center gap-2">
              <Button onClick={() => setTemplateOpen(true)}>✨ 从模板创建</Button>
              <Button variant="secondary" onClick={handleOpenCreate}>
                ➕ 新建专家
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <div
                role="tablist"
                aria-label="按来源筛选专家"
                className="flex items-center gap-1 rounded-lg border border-border bg-bg-subtle/50 p-1"
              >
                {SOURCE_FILTERS.map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={sourceFilter === key}
                    onClick={() => setSourceFilter(key)}
                    className={`rounded-md px-3 py-1 text-sm transition-colors ${
                      sourceFilter === key
                        ? 'bg-surface font-medium text-text shadow-sm'
                        : 'text-muted hover:text-text'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <input
                type="search"
                data-testid="specialists-search"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索专家名称或标语…"
                aria-label="搜索专家"
                className="min-w-0 flex-1 rounded-radius-md border border-border bg-surface px-3 py-1.5 text-sm outline-none focus:border-primary sm:max-w-xs"
              />
              <button
                type="button"
                onClick={toggleSelectionMode}
                className="rounded-radius-md border border-border px-3 py-1.5 text-sm hover:bg-bg-hover"
              >
                {selectionMode ? '退出批量' : '批量管理'}
              </button>
            </div>

            {selectionMode && (
              <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
                <span className="text-sm text-muted">已选 {selectedIds.size} 位</span>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={batchBusy || selectedIds.size === 0}
                  onClick={() => void handleBatch('enable')}
                >
                  启用
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={batchBusy || selectedIds.size === 0}
                  onClick={() => void handleBatch('disable')}
                >
                  禁用
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={batchBusy || selectedIds.size === 0}
                  onClick={() => void handleBatch('delete')}
                >
                  删除
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto"
                  disabled={batchBusy}
                  onClick={toggleSelectionMode}
                >
                  取消
                </Button>
              </div>
            )}

            {filteredAgents.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border bg-bg-subtle/40 p-8 text-center">
                <p className="text-sm text-muted">
                  {searchQuery.trim() ? '没有匹配的专家' : '该分类下暂无专家'}
                </p>
                {hasActiveFilters && (
                  <button
                    type="button"
                    onClick={() => {
                      setSourceFilter('all');
                      setSearchQuery('');
                    }}
                    className="mt-3 rounded-radius-md border border-border px-3 py-1.5 text-sm hover:bg-bg-hover"
                  >
                    清除筛选
                  </button>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {filteredAgents.map((agent) => (
                  <SpecialistCard
                    key={agent.id}
                    agent={agent}
                    onChat={handleStartChat}
                    onEdit={handleEdit}
                    onKnowledge={handleKnowledge}
                    onAssets={handleAssets}
                    onExport={handleExport}
                    onVersions={handleVersions}
                    onEval={handleEval}
                    exporting={exportingId === agent.id}
                    selectable={selectionMode && !PROTECTED_AGENT_IDS.has(agent.id)}
                    selected={selectedIds.has(agent.id)}
                    onSelectToggle={() => toggleSelect(agent.id)}
                    onOpenDetail={(next) => navigate(`/specialists/${next.id}`)}
                    onPin={(next) => void handlePin(next)}
                    onStartChat={(next) => void handleStartChat(next)}
                  />
                ))}
              </div>
            )}
          </>
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

      <KnowledgeBindingsEditor
        open={knowledgeAgent !== null}
        onOpenChange={(open) => {
          if (!open) setKnowledgeAgent(null);
        }}
        agent={knowledgeAgent}
        onChanged={loadAgents}
      />

      <SpecialistAssetsDialog
        open={assetsAgent !== null}
        onOpenChange={(open) => {
          if (!open) setAssetsAgent(null);
        }}
        agent={assetsAgent}
        onManageKnowledge={(agent) => {
          setAssetsAgent(null);
          setKnowledgeAgent(agent);
        }}
      />

      <TemplateGalleryDialog
        open={templateOpen}
        onOpenChange={setTemplateOpen}
        onCreated={() => void loadAgents()}
      />

      <GroupChatDialog
        open={groupChatOpen}
        onOpenChange={setGroupChatOpen}
        onCreated={() => navigate('/chat')}
      />

      <VersionHistoryDialog
        open={versionsAgent !== null}
        onOpenChange={(open) => {
          if (!open) setVersionsAgent(null);
        }}
        agent={versionsAgent}
        onRolledBack={() => void loadAgents()}
      />

      <SpecialistEvalDialog
        open={evalAgent !== null}
        onOpenChange={(open) => {
          if (!open) setEvalAgent(null);
        }}
        agent={evalAgent}
      />
    </div>
  );
}
