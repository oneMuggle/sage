/**
 * 专家详情页（P2-c）。
 *
 * 路由：``/specialists/:id``。展示单个专家的完整信息：
 * - 头部：头像 / 名称 / 标语 / 徽标 + 试聊 / 编辑 / 返回
 * - Tab：概览（统计）/ 人设（六段只读）/ 能力（技能 + 工具）/ 管理（知识·资产·版本·评测）
 *
 * 管理动作复用既有对话框组件（KnowledgeBindingsEditor / SpecialistAssetsDialog /
 * VersionHistoryDialog / SpecialistEvalDialog），避免重复实现。
 */
import { ArrowLeft, Pencil } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { PERSONA_SECTIONS, parsePersonaSections } from '../entities/specialist/personaSections';
import { describeToolSelection } from '../entities/specialist/toolCapabilities';
import { agentsApi, sessionApi, type AgentProfile } from '../shared/api';
import { useStore } from '../shared/lib/store';
import { Button } from '../shared/ui';
import { ErrorState } from '../shared/ui/ErrorState';
import { LoadingState } from '../shared/ui/LoadingState';
import { KnowledgeBindingsEditor } from '../widgets/specialists/KnowledgeBindingsEditor';
import { SpecialistAssetsDialog } from '../widgets/specialists/SpecialistAssetsDialog';
import { PERMISSION_MODE_LABELS } from '../widgets/specialists/SpecialistCard';
import { SpecialistEvalDialog } from '../widgets/specialists/SpecialistEvalDialog';
import { SpecialistWizard } from '../widgets/specialists/SpecialistWizard';
import { VersionHistoryDialog } from '../widgets/specialists/VersionHistoryDialog';

type DetailTab = 'overview' | 'persona' | 'abilities' | 'manage';

const TABS: ReadonlyArray<{ key: DetailTab; label: string }> = [
  { key: 'overview', label: '概览' },
  { key: 'persona', label: '人设' },
  { key: 'abilities', label: '能力' },
  { key: 'manage', label: '管理' },
];

const DEFAULT_AVATAR = '🤖';

function readUiString(ui: Record<string, unknown> | undefined, key: string): string {
  const value = ui?.[key];
  return typeof value === 'string' ? value.trim() : '';
}

export function SpecialistDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [agent, setAgent] = useState<AgentProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>('overview');

  // 管理动作对话框
  const [wizardOpen, setWizardOpen] = useState(false);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [assetsOpen, setAssetsOpen] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [evalOpen, setEvalOpen] = useState(false);

  const loadAgent = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const list = await agentsApi.list();
      const found = list.find((a) => a.id === id) ?? null;
      setAgent(found);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void loadAgent();
  }, [loadAgent]);

  const sections = useMemo(
    () => (agent ? parsePersonaSections(agent.system_prompt ?? '') : null),
    [agent],
  );

  async function handleStartChat() {
    if (!agent) return;
    try {
      const sid = await useStore.getState().createSession();
      await sessionApi.setSpecialist(sid, agent.id);
      useStore.getState().updateSession(sid, { specialist_id: agent.id });
      navigate('/chat');
    } catch (err) {
      toast.error(`进入试聊失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }

  if (loading) {
    return (
      <div className="flex-1 overflow-auto">
        <LoadingState label="加载专家…" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 overflow-auto">
        <ErrorState message={error} onRetry={loadAgent} />
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="flex-1 overflow-auto">
        <div className="mx-auto max-w-3xl px-6 py-10 text-center">
          <p className="text-sm text-muted">未找到该专家（可能已被删除）。</p>
          <Button className="mt-4" variant="secondary" onClick={() => navigate('/specialists')}>
            返回专家列表
          </Button>
        </div>
      </div>
    );
  }

  const avatar = readUiString(agent.persona_ui, 'avatar') || DEFAULT_AVATAR;
  const tagline = readUiString(agent.persona_ui, 'tagline') || agent.description;
  const skillCount = agent.skills?.length ?? 0;
  const tools = agent.tools ?? [];
  const toolSummary = describeToolSelection(tools);
  const lastUsedDaysAgo =
    typeof agent.last_used_at === 'number' && agent.last_used_at > 0
      ? Math.floor((Date.now() - agent.last_used_at) / (1000 * 60 * 60 * 24))
      : null;

  return (
    <div className="flex-1 overflow-auto">
      <div className="mx-auto max-w-4xl px-6 py-6">
        <button
          type="button"
          onClick={() => navigate('/specialists')}
          className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-text"
        >
          <ArrowLeft className="h-4 w-4" /> 返回专家列表
        </button>

        {/* 头部 */}
        <div className="flex flex-wrap items-start gap-4 rounded-xl border border-border bg-surface p-5">
          <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg bg-bg-subtle text-4xl">
            {avatar}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-medium">{agent.name}</h1>
              <span className="rounded-full bg-bg-subtle px-2 py-0.5 text-ui-xs text-muted">
                v{agent.version ?? 1}
              </span>
              {!agent.enabled && (
                <span className="rounded-full bg-warning/20 px-2 py-0.5 text-ui-xs text-warning">
                  ⚠️ 已禁用
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-muted">{tagline || '尚未填写标语'}</p>
            <p className="mt-1 text-ui-xs text-faint">
              {agent.source === 'builtin'
                ? '内置'
                : agent.source === 'imported'
                  ? '导入'
                  : '用户创建'}
              {agent.permission_mode ? ` · ${PERMISSION_MODE_LABELS[agent.permission_mode]}` : ''}
              {` · ${skillCount} 项技能`}
              {tools.length === 0 ? ' · 纯对话（无工具）' : ` · ${tools.length} 项工具`}
              {lastUsedDaysAgo !== null
                ? ` · ${lastUsedDaysAgo === 0 ? '今天使用' : `${lastUsedDaysAgo} 天前使用`}`
                : ' · 未使用过'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="md"
              disabled={!agent.enabled}
              onClick={() => void handleStartChat()}
            >
              💬 开始试聊
            </Button>
            <Button variant="secondary" size="md" onClick={() => setWizardOpen(true)}>
              <Pencil className="mr-1 h-4 w-4" /> 编辑
            </Button>
          </div>
        </div>

        {/* Tab 栏 */}
        <div
          role="tablist"
          aria-label="专家详情"
          className="mt-5 flex items-center gap-1 rounded-lg border border-border bg-bg-subtle/50 p-1"
        >
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={activeTab === key}
              onClick={() => setActiveTab(key)}
              className={`rounded-md px-4 py-1.5 text-sm transition-colors ${
                activeTab === key
                  ? 'bg-surface font-medium text-text shadow-sm'
                  : 'text-muted hover:text-text'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Tab 内容 */}
        <div className="mt-4">
          {activeTab === 'overview' && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                { label: '技能', value: `${skillCount}` },
                { label: '版本', value: `v${agent.version ?? 1}` },
                {
                  label: '最近使用',
                  value:
                    lastUsedDaysAgo === null
                      ? '从未'
                      : lastUsedDaysAgo === 0
                        ? '今天'
                        : `${lastUsedDaysAgo} 天前`,
                },
                {
                  label: '状态',
                  value: agent.enabled ? '已启用' : '已禁用',
                },
              ].map((item) => (
                <div
                  key={item.label}
                  className="rounded-lg border border-border bg-surface p-3 text-center"
                >
                  <div className="text-lg font-medium">{item.value}</div>
                  <div className="mt-0.5 text-ui-xs text-muted">{item.label}</div>
                </div>
              ))}
            </div>
          )}

          {activeTab === 'persona' && sections && (
            <div className="flex flex-col gap-3">
              {PERSONA_SECTIONS.map((meta) => (
                <div key={meta.key} className="rounded-lg border border-border bg-surface p-4">
                  <h3 className="text-sm font-medium">{meta.label}</h3>
                  <p className="mt-1 whitespace-pre-wrap break-words text-sm text-muted">
                    {sections[meta.key]?.trim() || '（未填写）'}
                  </p>
                </div>
              ))}
            </div>
          )}

          {activeTab === 'abilities' && (
            <div className="flex flex-col gap-3">
              <div className="rounded-lg border border-border bg-surface p-4">
                <h3 className="text-sm font-medium">技能</h3>
                {skillCount === 0 ? (
                  <p className="mt-1 text-sm text-muted">
                    未配置技能。点「编辑」在向导第 3 步勾选。
                  </p>
                ) : (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(agent.skills ?? []).map((skill) => (
                      <span
                        key={skill}
                        className="rounded-full border border-border px-2.5 py-1 text-ui-xs text-text-secondary"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div
                className="rounded-lg border border-border bg-surface p-4"
                data-testid="specialist-detail-tools"
              >
                <h3 className="text-sm font-medium">工具能力</h3>
                {tools.length === 0 ? (
                  <p className="mt-1 text-sm text-warning">
                    纯对话专家：未授权任何工具，运行时所有工具调用都会被拒绝（包括读取文件）。
                    点「编辑」在向导第 3 步选择能力包。
                  </p>
                ) : (
                  <>
                    <p className="mt-1 text-ui-xs text-muted">共 {tools.length} 项工具</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {toolSummary.covered.map((pack) => (
                        <span
                          key={pack.id}
                          className="rounded-full bg-primary/10 px-2.5 py-1 text-ui-xs text-primary"
                        >
                          {pack.label}
                        </span>
                      ))}
                      {toolSummary.partial.map((pack) => (
                        <span
                          key={pack.id}
                          className="rounded-full border border-border px-2.5 py-1 text-ui-xs text-text-secondary"
                        >
                          {pack.label}（部分）
                        </span>
                      ))}
                    </div>
                    {toolSummary.uncategorized.length > 0 && (
                      <p className="mt-2 break-all font-mono text-ui-xs text-faint">
                        未归类：{toolSummary.uncategorized.join('、')}
                      </p>
                    )}
                  </>
                )}
              </div>
            </div>
          )}

          {activeTab === 'manage' && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {[
                {
                  label: '知识绑定',
                  desc: '接入项目资料 / Wiki / Zotero 等知识源',
                  onClick: () => setKnowledgeOpen(true),
                },
                {
                  label: '资产中心',
                  desc: '私有记忆 / 知识 / 技能总览与手动追加记忆',
                  onClick: () => setAssetsOpen(true),
                },
                {
                  label: '版本历史',
                  desc: '查看字段级 diff 并回滚到历史版本',
                  onClick: () => setVersionsOpen(true),
                },
                {
                  label: '黄金任务评测',
                  desc: '用内置任务集评估专家回答质量',
                  onClick: () => setEvalOpen(true),
                },
              ].map((item) => (
                <button
                  key={item.label}
                  type="button"
                  onClick={item.onClick}
                  className="rounded-lg border border-border bg-surface p-4 text-left transition-colors hover:border-border-hover hover:bg-bg-hover"
                >
                  <div className="text-sm font-medium">{item.label}</div>
                  <div className="mt-0.5 text-ui-xs text-muted">{item.desc}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <SpecialistWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        editingAgent={agent}
        onSaved={() => void loadAgent()}
      />
      <KnowledgeBindingsEditor
        open={knowledgeOpen}
        onOpenChange={setKnowledgeOpen}
        agent={agent}
        onChanged={() => void loadAgent()}
      />
      <SpecialistAssetsDialog
        open={assetsOpen}
        onOpenChange={setAssetsOpen}
        agent={agent}
        onManageKnowledge={() => {
          setAssetsOpen(false);
          setKnowledgeOpen(true);
        }}
      />
      <VersionHistoryDialog
        open={versionsOpen}
        onOpenChange={setVersionsOpen}
        agent={agent}
        onRolledBack={() => void loadAgent()}
      />
      <SpecialistEvalDialog open={evalOpen} onOpenChange={setEvalOpen} agent={agent} />
    </div>
  );
}
