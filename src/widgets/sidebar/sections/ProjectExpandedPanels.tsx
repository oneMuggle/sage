import {
  CheckSquare,
  FilePlus2,
  FileText,
  History,
  Plus,
  Save,
  Search,
  ShieldPlus,
  Sparkles,
  Square,
  Trash2,
} from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { ProjectOverviewWidgets } from '../../../features/project-type/ProjectOverviewWidgets';
import {
  projectApi,
  type ProjectMaterial,
  type ProjectSummary,
  type ProjectType,
} from '../../../shared/api/projectApi';
import { useI18n } from '../../../shared/lib/i18n';
import { formatRelativeTime } from '../../../shared/lib/utils';

import { MaterialStatusBadge } from './MaterialStatusBadge';

const SIDEBAR_L2_PRESETS: Record<
  ProjectType,
  Array<{ label: string; description: string; instructions: string }>
> = {
  coding: [
    {
      label: '严格类型与单测门禁',
      description: '全栈工程研发与模块化重构，保持零架构回归',
      instructions: '所有新增逻辑必须附带类型定义与单元测试，严禁引入静默异常吞噬。',
    },
    {
      label: '增量重构与小步提交',
      description: '遗留系统渐进式解耦与性能调优',
      instructions: '遵循最小改动面原则，先补充回归单测再修改核心路径，禁止破坏现有公开接口。',
    },
  ],
  business: [
    {
      label: '法务合同与双轨校核',
      description: '商务合同起草、公文签报与多轮合规审校',
      instructions: '严格核对大小写金额、关键日期与违约责任条款，遵循 GB/T 9704 公文格式规范。',
    },
    {
      label: '立卷归档与封卷审计',
      description: '政企项目全周期文书立卷与审计备查归档',
      instructions: '未签批定稿件严禁移入正式归档目录，所有修订意见必须留存对照记录。',
    },
  ],
  research: [
    {
      label: '零幻觉文献与实验复现',
      description: '学术论文撰述、定量对比实验与可复现消融分析',
      instructions:
        '采用严谨客观的学术被动语态，所有文献引用必须真实可查，固定并记录全部实验随机种子。',
    },
    {
      label: '审稿回复与图表溯源',
      description: '期刊与顶会审稿意见逐条回复及补充实验验证',
      instructions:
        '逐条采用 Point-by-Point 结构礼貌回应审稿人，正文所有修订段落显式标注变更位置。',
    },
  ],
  personal: [
    {
      label: '卡片盒笔记与行动提取',
      description: '个人双链知识库沉淀、阅读摘录卡片化与行动清单闭环',
      instructions:
        '每张永久笔记仅阐述一个原子概念，使用 [[双链]] 关联已有卡片，并在末尾提炼可执行行动项。',
    },
    {
      label: '长文创作与风格一致',
      description: '专题文章连载、深度读书笔记与跨主题知识综合',
      instructions: '保持自然流畅的个人叙事风格，引用原始素材时保留出处时间戳与上下文锚点。',
    },
  ],
};

interface OverviewDraftEntry {
  description: string;
  instructions: string;
  dirty: boolean;
}

interface ProjectOverviewPanelProps {
  project: ProjectSummary;
  draft: OverviewDraftEntry | undefined;
  saving: boolean;
  onSave: (project: ProjectSummary) => void;
  onChange: (projectId: string, field: 'description' | 'instructions', value: string) => void;
}

export function ProjectOverviewPanel({
  project,
  draft,
  saving,
  onSave,
  onChange,
}: ProjectOverviewPanelProps) {
  const { t } = useI18n();
  const [creatingCheckpoint, setCreatingCheckpoint] = useState(false);
  const [savedOverviewL3, setSavedOverviewL3] = useState(false);
  const [savedOverviewL2, setSavedOverviewL2] = useState(false);
  const archetype: ProjectType = project.projectType ?? project.detectedType ?? 'coding';
  const presets = SIDEBAR_L2_PRESETS[archetype] ?? SIDEBAR_L2_PRESETS.coding;

  const handleQuickCheckpoint = async () => {
    if (creatingCheckpoint || typeof projectApi?.createCheckpoint !== 'function') return;
    setCreatingCheckpoint(true);
    try {
      const cp = await projectApi.createCheckpoint(project.id, '侧边栏快速版本快照');
      toast.success(`已创建版本快照：${cp.id}`);
    } catch {
      // ignore in test/offline mode
    } finally {
      setCreatingCheckpoint(false);
    }
  };

  const handleSaveOverviewToL3 = async () => {
    if (savedOverviewL3) return;
    setSavedOverviewL3(true);
    const desc = (draft?.description ?? project.description ?? '').trim();
    const inst = (draft?.instructions ?? project.instructions ?? '').trim();
    const summary = `[项目目标与指令] 目标: ${desc || '未设置'} | 指令: ${inst || '未设置'}`;
    if (typeof projectApi?.confirmKnowledge !== 'function') return;
    try {
      await projectApi.confirmKnowledge(project.id, {
        entries: [
          {
            category: 'goal',
            content: summary.slice(0, 300),
            importance: 8,
            sourceMessageIds: [],
            reasoning: '项目目标与指令保存至 AI 记忆',
          },
        ],
      });
    } catch {
      // ignore in test/offline mode
    }
  };

  return (
    <div
      className="ml-5 mr-1.5 mt-1 p-2 rounded border border-border/50 bg-bg/40"
      data-testid="project-overview-panel"
    >
      {Boolean(project.projectType || project.detectedType) && (
        <div className="mb-2" data-testid="project-overview-widgets-slot">
          <ProjectOverviewWidgets project={project} />
        </div>
      )}
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-ui-2xs text-muted uppercase tracking-wide">
          {t('sider.project.overview_title')}
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            data-testid="sidebar-overview-save-l3"
            onClick={() => void handleSaveOverviewToL3()}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-ui-2xs text-primary hover:bg-primary/10"
            title="将当前项目目标与指令保存到 AI 记忆"
          >
            {savedOverviewL3 ? '已保存' : '保存到 AI 记忆'}
          </button>
          <button
            type="button"
            data-testid="sidebar-overview-to-constraint"
            onClick={async () => {
              if (savedOverviewL2) return;
              setSavedOverviewL2(true);
              const desc = (draft?.description ?? project.description ?? '').trim();
              const inst = (draft?.instructions ?? project.instructions ?? '').trim();
              if (typeof projectApi?.createConstraint !== 'function') return;
              try {
                await projectApi.createConstraint(project.id, {
                  category: 'convention',
                  content: `项目目标与指令约束：${desc || '核心目标'} — ${inst || '遵循项目规范'}`,
                  priority: 8,
                });
              } catch {
                // ignore in test/offline mode
              }
            }}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-ui-2xs text-muted hover:text-text hover:bg-bg-hover"
          >
            {savedOverviewL2 ? '已保存' : '保存为项目规则'}
          </button>
          {project.vcsMode !== 'git' && project.projectType !== 'coding' && (
            <button
              type="button"
              data-testid="sidebar-quick-checkpoint-btn"
              disabled={creatingCheckpoint}
              onClick={() => void handleQuickCheckpoint()}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-ui-2xs text-emerald-600 hover:bg-emerald-500/10 disabled:opacity-40"
            >
              <History className="w-3 h-3" aria-hidden="true" />
              {creatingCheckpoint ? '快照中...' : '新建快照'}
            </button>
          )}
          <button
            type="button"
            data-testid="project-overview-save"
            disabled={!draft?.dirty || saving}
            onClick={() => onSave(project)}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-ui-2xs text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Save className="w-3 h-3" aria-hidden="true" />
            {saving ? t('sider.project.overview_saving') : t('sider.project.overview_save')}
          </button>
        </div>
      </div>
      <div
        className="mb-1.5 flex flex-wrap items-center gap-1"
        data-testid="sidebar-overview-presets"
      >
        <span className="inline-flex items-center gap-0.5 text-ui-2xs text-muted">
          <Sparkles className="w-2.5 h-2.5 text-primary" aria-hidden="true" />
          快捷模板：
        </span>
        {presets.map((p, idx) => (
          <button
            key={p.label}
            type="button"
            data-testid={`sidebar-overview-preset-${idx}`}
            onClick={() => {
              onChange(project.id, 'description', p.description);
              onChange(project.id, 'instructions', p.instructions);
            }}
            className="rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 text-ui-2xs text-primary hover:bg-primary/10"
          >
            {p.label}
          </button>
        ))}
      </div>
      <label className="block text-ui-2xs text-muted mb-0.5">
        {t('sider.project.overview_description')}
      </label>
      <textarea
        data-testid="project-overview-description"
        value={draft?.description ?? ''}
        onChange={(e) => onChange(project.id, 'description', e.target.value)}
        rows={2}
        className="w-full text-ui-2xs px-1.5 py-1 rounded border border-border bg-bg resize-y"
        placeholder={t('sider.project.overview_description_placeholder')}
      />
      <label className="block text-ui-2xs text-muted mb-0.5 mt-1.5">
        {t('sider.project.overview_instructions')}
      </label>
      <textarea
        data-testid="project-overview-instructions"
        value={draft?.instructions ?? ''}
        onChange={(e) => onChange(project.id, 'instructions', e.target.value)}
        rows={3}
        className="w-full text-ui-2xs px-1.5 py-1 rounded border border-border bg-bg resize-y"
        placeholder={t('sider.project.overview_instructions_placeholder')}
      />
    </div>
  );
}

interface ProjectMaterialsPanelProps {
  project: ProjectSummary;
  list: ProjectMaterial[] | undefined;
  isLoading: boolean;
  isAdding: boolean;
  draftText: string;
  currentSessionId: string | null;
  savingAnswer: boolean;
  removingMaterialId: string | null;
  onSaveAnswer: (project: ProjectSummary) => void;
  onRemoveMaterial: (project: ProjectSummary, materialId: string) => void;
  onDraftChange: (projectId: string, text: string) => void;
  onAddMaterial: (project: ProjectSummary) => void;
}

const MATERIAL_PER_FILE_CAP = 8000;
const MATERIAL_TOTAL_CAP = 16000;

export function ProjectMaterialsPanel({
  project,
  list,
  isLoading,
  isAdding,
  draftText,
  currentSessionId,
  savingAnswer,
  removingMaterialId,
  onSaveAnswer,
  onRemoveMaterial,
  onDraftChange,
  onAddMaterial,
}: ProjectMaterialsPanelProps) {
  const { t } = useI18n();
  const [enabledOverrides, setEnabledOverrides] = useState<Record<string, boolean>>({});
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [filePathInput, setFilePathInput] = useState('');
  const [addingFromFile, setAddingFromFile] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'enabled' | 'disabled'>('all');
  const [promotedConstraintIds, setPromotedConstraintIds] = useState<Set<string>>(new Set());
  const [promotedProfileMaterialIds, setPromotedProfileMaterialIds] = useState<Set<string>>(
    new Set(),
  );
  const [promotedMilestoneMaterialIds, setPromotedMilestoneMaterialIds] = useState<Set<string>>(
    new Set(),
  );

  const handleAddFromFile = async () => {
    const rel = filePathInput.trim();
    if (!rel || addingFromFile || typeof projectApi.addMaterialFromFile !== 'function') return;
    setAddingFromFile(true);
    try {
      await projectApi.addMaterialFromFile(project.id, rel);
      setFilePathInput('');
      toast.success(`已将工作区文件纳入资料池: ${rel}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '导入工作区文件失败');
    } finally {
      setAddingFromFile(false);
    }
  };

  const isMaterialEnabled = (m: ProjectMaterial): boolean => {
    if (m.id in enabledOverrides) return enabledOverrides[m.id];
    return m.enabled !== false;
  };

  const handleBatchToggleMaterials = async (nextEnabled: boolean) => {
    const readyList = (list ?? []).filter((m) => m.status === 'ready');
    if (readyList.length === 0) return;
    const nextMap: Record<string, boolean> = {};
    for (const item of readyList) {
      nextMap[item.id] = nextEnabled;
    }
    setEnabledOverrides((prev) => ({ ...prev, ...nextMap }));
    if (typeof projectApi.updateMaterial !== 'function') return;
    for (const item of readyList) {
      try {
        await projectApi.updateMaterial(project.id, item.id, { enabled: nextEnabled });
      } catch {
        // ignore in test/offline mode
      }
    }
  };

  const handleToggleMaterial = async (m: ProjectMaterial) => {
    if (togglingId === m.id) return;
    const nextEnabled = !isMaterialEnabled(m);
    setEnabledOverrides((prev) => ({ ...prev, [m.id]: nextEnabled }));
    if (typeof projectApi.updateMaterial !== 'function') return;
    setTogglingId(m.id);
    try {
      await projectApi.updateMaterial(project.id, m.id, { enabled: nextEnabled });
    } catch (err) {
      setEnabledOverrides((prev) => ({ ...prev, [m.id]: !nextEnabled }));
      toast.error(err instanceof Error ? err.message : '切换资料状态失败');
    } finally {
      setTogglingId(null);
    }
  };

  const readyMaterials = (list ?? []).filter((m) => m.status === 'ready');
  const activeReadyMaterials = readyMaterials.filter((m) => isMaterialEnabled(m));
  const usedChars = Math.min(
    MATERIAL_TOTAL_CAP,
    activeReadyMaterials.reduce(
      (acc, m) => acc + Math.min((m.content ?? '').length, MATERIAL_PER_FILE_CAP),
      0,
    ),
  );
  const usagePct = Math.min(100, Math.round((usedChars / MATERIAL_TOTAL_CAP) * 100));

  const q = searchQuery.trim().toLowerCase();
  const filteredList = (list ?? []).filter((m) => {
    const enabled = isMaterialEnabled(m);
    if (statusFilter === 'enabled' && !enabled) return false;
    if (statusFilter === 'disabled' && enabled) return false;
    if (!q) return true;
    return (
      (m.content ?? '').toLowerCase().includes(q) ||
      (m.sourceMessageId ?? '').toLowerCase().includes(q) ||
      m.id.toLowerCase().includes(q)
    );
  });

  return (
    <div
      className="ml-5 mr-1.5 mt-1 p-2 rounded border border-border/50 bg-bg/40"
      data-testid="project-materials-panel"
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-ui-2xs text-muted uppercase tracking-wide">
          {t('sider.project.materials_title')}
        </span>
        <button
          type="button"
          data-testid="project-save-answer"
          disabled={savingAnswer || !currentSessionId}
          onClick={() => onSaveAnswer(project)}
          title={
            currentSessionId
              ? t('sider.project.save_answer_title')
              : t('sider.project.save_answer_no_session')
          }
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-ui-2xs text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          <FilePlus2 className="w-3 h-3" aria-hidden="true" />
          {t('sider.project.save_answer')}
        </button>
      </div>

      {list && list.length > 0 && (
        <div
          className="mb-2 px-1.5 py-1 rounded bg-bg-muted/60 border border-border/40"
          data-testid="project-materials-watermark"
        >
          <div className="flex items-center justify-between text-ui-2xs text-text-secondary">
            <span>
              受控注入源 · 已启用 {activeReadyMaterials.length}/{readyMaterials.length}
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                data-testid="sidebar-materials-enable-all"
                onClick={() => void handleBatchToggleMaterials(true)}
                className="rounded border border-border/60 bg-bg px-1 py-0.5 text-ui-2xs text-text-secondary hover:text-text"
              >
                全选
              </button>
              <button
                type="button"
                data-testid="sidebar-materials-disable-all"
                onClick={() => void handleBatchToggleMaterials(false)}
                className="rounded border border-border/60 bg-bg px-1 py-0.5 text-ui-2xs text-text-secondary hover:text-text"
              >
                全停
              </button>
              <span className="tabular-nums text-muted">
                {usedChars.toLocaleString()} / {MATERIAL_TOTAL_CAP.toLocaleString()} 字 ({usagePct}
                %)
              </span>
            </div>
          </div>
          <div className="mt-1 h-1 w-full rounded-full bg-border/50 overflow-hidden">
            <div
              className={`h-full transition-all ${
                usagePct >= 90 ? 'bg-danger' : usagePct >= 70 ? 'bg-warning' : 'bg-primary'
              }`}
              style={{ width: `${Math.max(usagePct, activeReadyMaterials.length > 0 ? 4 : 0)}%` }}
            />
          </div>
        </div>
      )}

      {list && list.length > 0 && (
        <div className="mb-1.5 space-y-1">
          <div className="flex items-center gap-1" data-testid="sidebar-materials-filter-bar">
            {(
              [
                { id: 'all', label: '全部' },
                { id: 'enabled', label: '已启用' },
                { id: 'disabled', label: '已暂停' },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                data-testid={`sidebar-materials-filter-${tab.id}`}
                onClick={() => setStatusFilter(tab.id)}
                className={`rounded px-1.5 py-0.5 text-ui-2xs transition-colors ${
                  statusFilter === tab.id
                    ? 'bg-primary text-primary-foreground font-medium'
                    : 'bg-bg text-muted hover:text-text'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="relative">
            <Search className="w-3 h-3 text-muted absolute left-1.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索侧边栏资料内容或消息来源..."
              data-testid="sidebar-materials-search-input"
              className="w-full text-ui-2xs pl-5 pr-1.5 py-0.5 rounded border border-border bg-bg"
            />
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-ui-2xs text-muted py-1" data-testid="project-materials-loading">
          {t('sider.project.materials_loading')}
        </div>
      ) : list && list.length > 0 ? (
        <ul className="space-y-1" data-testid="project-material-list">
          {filteredList.map((m) => {
            const enabled = isMaterialEnabled(m);
            return (
              <li
                key={m.id}
                data-testid="project-material-row"
                data-status={m.status}
                data-enabled={String(enabled)}
                className={`flex items-start gap-1.5 px-1.5 py-1 rounded bg-bg/60 border border-border/30 transition-opacity ${
                  enabled ? '' : 'opacity-60'
                }`}
              >
                <button
                  type="button"
                  data-testid="project-material-toggle"
                  aria-pressed={enabled}
                  aria-label={enabled ? '暂停注入此资料' : '启用注入此资料'}
                  title={enabled ? '已参与本轮上下文注入（点击暂停）' : '已暂停注入（点击启用）'}
                  disabled={togglingId === m.id}
                  onClick={() => void handleToggleMaterial(m)}
                  className="mt-0.5 shrink-0 inline-flex items-center justify-center text-muted hover:text-primary disabled:opacity-40"
                >
                  {enabled ? (
                    <CheckSquare className="w-3.5 h-3.5 text-primary" aria-hidden="true" />
                  ) : (
                    <Square className="w-3.5 h-3.5" aria-hidden="true" />
                  )}
                </button>
                <FileText className="w-3 h-3 mt-0.5 shrink-0 text-muted" aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 text-ui-2xs">
                    <MaterialStatusBadge status={m.status} />
                    <span className="text-muted truncate">
                      {m.sourceMessageId
                        ? t('sider.project.material_from_message').replace(
                            '{id}',
                            m.sourceMessageId,
                          )
                        : t('sider.project.material_direct')}
                    </span>
                    <span className="text-muted/60 tabular-nums ml-auto">
                      {formatRelativeTime(m.createdAt)}
                    </span>
                  </div>
                  {m.status === 'failed' && m.errorMessage && (
                    <div
                      className="text-ui-2xs text-warning mt-0.5 truncate"
                      title={m.errorMessage}
                      data-testid="project-material-error"
                    >
                      {m.errorMessage}
                    </div>
                  )}
                  {m.status === 'ready' && m.content && (
                    <div className="text-ui-2xs text-text-secondary mt-0.5 line-clamp-2">
                      {m.content.slice(0, 120)}
                      {m.content.length > 120 ? '…' : ''}
                    </div>
                  )}
                </div>
                {m.status === 'ready' && m.content && (
                  <button
                    type="button"
                    data-testid={`sidebar-material-to-l3-${m.id}`}
                    onClick={async () => {
                      if (promotedProfileMaterialIds.has(m.id)) return;
                      setPromotedProfileMaterialIds((prev) => new Set(prev).add(m.id));
                      if (typeof projectApi?.confirmKnowledge !== 'function') return;
                      try {
                        await projectApi.confirmKnowledge(project.id, {
                          entries: [
                            {
                              category: 'note',
                              content: `[项目资料摘录] ${(m.content ?? '').slice(0, 200)}`,
                              importance: 7,
                              sourceMessageIds: [],
                              reasoning: '项目资料保存至 AI 记忆',
                            },
                          ],
                        });
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    title="保存到 AI 记忆"
                    className="shrink-0 inline-flex items-center gap-0.5 rounded border border-border/60 bg-bg px-1 py-0.5 text-ui-2xs text-muted hover:text-primary"
                  >
                    {promotedProfileMaterialIds.has(m.id) ? '已保存' : '保存到记忆'}
                  </button>
                )}
                {m.status === 'ready' && m.content && (
                  <button
                    type="button"
                    data-testid={`sidebar-material-to-constraint-${m.id}`}
                    onClick={async () => {
                      if (promotedConstraintIds.has(m.id)) return;
                      setPromotedConstraintIds((prev) => new Set(prev).add(m.id));
                      if (typeof projectApi?.createConstraint !== 'function') return;
                      try {
                        await projectApi.createConstraint(project.id, {
                          category: 'custom',
                          content: (m.content ?? '').slice(0, 200),
                          priority: 7,
                        });
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    title="保存为项目规则"
                    className="shrink-0 inline-flex items-center gap-0.5 rounded border border-border/60 bg-bg px-1 py-0.5 text-ui-2xs text-muted hover:text-primary"
                  >
                    <ShieldPlus className="w-2.5 h-2.5" aria-hidden="true" />
                    {promotedConstraintIds.has(m.id) ? '已保存' : '保存为规则'}
                  </button>
                )}
                {m.status === 'ready' && m.content && (
                  <button
                    type="button"
                    data-testid={`sidebar-material-to-milestone-${m.id}`}
                    onClick={async () => {
                      if (promotedMilestoneMaterialIds.has(m.id)) return;
                      setPromotedMilestoneMaterialIds((prev) => new Set(prev).add(m.id));
                      if (typeof projectApi?.createMilestone !== 'function') return;
                      try {
                        await projectApi.createMilestone(project.id, {
                          title: `[资料研读] ${(m.content ?? '').slice(0, 48)}`,
                          description: `源自项目资料 (${m.id})`,
                          status: 'pending',
                        });
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="shrink-0 inline-flex items-center gap-0.5 rounded border border-border/60 bg-bg px-1 py-0.5 text-ui-2xs text-muted hover:text-primary"
                  >
                    {promotedMilestoneMaterialIds.has(m.id) ? '已建里程碑' : '+里程碑'}
                  </button>
                )}
                <button
                  type="button"
                  data-testid="project-material-remove"
                  aria-label={t('sider.project.material_remove')}
                  disabled={removingMaterialId === m.id}
                  onClick={() => onRemoveMaterial(project, m.id)}
                  className="shrink-0 inline-flex items-center justify-center w-4 h-4 rounded text-muted hover:text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Trash2 className="w-3 h-3" aria-hidden="true" />
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="text-ui-2xs text-muted py-1" data-testid="project-materials-empty">
          {t('sider.project.materials_empty')}
        </div>
      )}

      {typeof projectApi.addMaterialFromFile === 'function' && (
        <div className="mt-2 flex items-center gap-1">
          <input
            type="text"
            data-testid="project-material-file-input"
            value={filePathInput}
            onChange={(e) => setFilePathInput(e.target.value)}
            placeholder="输入工作区相对路径一键入库 (如 01_literature/refs.bib 或 02_编制中工作稿/合同.docx)"
            className="flex-1 text-ui-2xs px-1.5 py-1 rounded border border-border bg-bg font-mono"
          />
          <button
            type="button"
            data-testid="project-material-file-add"
            disabled={addingFromFile || !filePathInput.trim()}
            onClick={() => void handleAddFromFile()}
            className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded border border-border/60 text-ui-2xs text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Plus className="w-3 h-3" aria-hidden="true" />
            导入文件
          </button>
        </div>
      )}

      <div className="mt-2 space-y-1">
        <textarea
          data-testid="project-material-input"
          value={draftText}
          onChange={(e) => onDraftChange(project.id, e.target.value)}
          rows={3}
          placeholder={t('sider.project.material_input_placeholder')}
          className="w-full text-ui-2xs px-1.5 py-1 rounded border border-border bg-bg resize-y"
        />
        <div className="flex justify-end">
          <button
            type="button"
            data-testid="project-material-add"
            disabled={isAdding || !draftText.trim()}
            onClick={() => onAddMaterial(project)}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-ui-2xs text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Plus className="w-3 h-3" aria-hidden="true" />
            {t('sider.project.material_add')}
          </button>
        </div>
      </div>
    </div>
  );
}

/** 子行前缀圆点：层级指示，弱于图标避免与主行混淆 */
export function MessageDot() {
  return (
    <span className="w-1 h-1 rounded-full bg-current opacity-40 shrink-0" aria-hidden="true" />
  );
}

/** 移除按钮图标：与 Folder 语义呼应，弱化"删除文件"的误读 */
export function FolderMinusIcon() {
  return (
    <svg
      className="h-4 w-4"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z" />
      <path d="M9 13h6" />
    </svg>
  );
}
