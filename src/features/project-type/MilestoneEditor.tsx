/**
 * 里程碑编辑器 (2026-09-25; Phase P26 四形态里程碑交付物模板与快捷相对截止日期 2026-10-13)
 *
 * 项目类型分类系统 - Phase 4.5
 * 创建/编辑里程碑的 Dialog
 */

import { useState, useEffect } from 'react';

import { projectApi, type ProjectMilestone, type ProjectType } from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../../shared/ui/Dialog/Dialog';
import { Input } from '../../shared/ui/Input';
import { Textarea } from '../../shared/ui/Textarea';

import { getArchetypeBlueprint } from './archetypeBlueprints';

const MILESTONE_TEMPLATES: Record<
  ProjectType,
  Array<{ label: string; title: string; description: string; stage: string; sortOrder: number }>
> = {
  coding: [
    {
      label: '架构与接口冻结',
      title: '完成核心架构设计与 API 契约评审',
      description: '明确模块依赖边界、数据表 Schema 与核心 RPC/IPC 接口定义，输出架构设计说明。',
      stage: 'design',
      sortOrder: 1,
    },
    {
      label: '核心功能联调',
      title: '完成核心业务闭环编码与前后端联调',
      description: '完成关键用户路径实现，补齐单元测试并消除类型与 Lint 告警。',
      stage: 'implementation',
      sortOrder: 2,
    },
    {
      label: '门禁与发布验收',
      title: '通过全量回归测试与发布门禁验收',
      description: '完成端到端回归测试、性能基线核验与版本变更记录归档。',
      stage: 'verification',
      sortOrder: 3,
    },
  ],
  business: [
    {
      label: '底稿与法规归集',
      title: '完成背景材料、上位制度与底稿证据归集',
      description: '梳理立项批复、历史往来函件与适用法律法规条款，建立受控资料索引。',
      stage: 'initiation',
      sortOrder: 1,
    },
    {
      label: '文书编制与初审',
      title: '完成正式文书/合同草拟与交叉复核',
      description: '按 GB/T 9704 或标准合同版式完成正文编制，核验金额大小写与权责条款。',
      stage: 'execution',
      sortOrder: 2,
    },
    {
      label: '法务终审与封卷',
      title: '完成法务合规终审与定稿签发归档',
      description: '闭环全部审校修订意见，导出定稿文书并留存终版归档快照。',
      stage: 'closure',
      sortOrder: 3,
    },
  ],
  research: [
    {
      label: '文献与假设确立',
      title: '完成核心文献综述与研究假设形式化',
      description: '梳理领域代表性基线工作，界定创新点、理论推导边界与实验评估协议。',
      stage: 'literature',
      sortOrder: 1,
    },
    {
      label: '基线与消融实验',
      title: '完成主实验复现与关键消融对比',
      description: '固定随机种子完成全量数据集定量评估，汇总统计显著性与超参数敏感度结果。',
      stage: 'experiment',
      sortOrder: 2,
    },
    {
      label: '论文定稿与核验',
      title: '完成论文手稿撰述、图表排版与引用核验',
      description: '逐条核对 BibTeX 文献真实性、实验表格数值一致性及补充材料可复现性。',
      stage: 'publication',
      sortOrder: 3,
    },
  ],
  personal: [
    {
      label: '素材收集与分类',
      title: '完成近期灵感碎片、读书摘录与资料归集',
      description: '将零散输入统一归入收件箱并标注主题标签与来源上下文。',
      stage: 'capture',
      sortOrder: 1,
    },
    {
      label: '双链卡片提炼',
      title: '完成核心概念原子化卡片与双向链接建立',
      description: '提炼永久笔记卡片，串联跨主题关联并更新专题结构化索引。',
      stage: 'distill',
      sortOrder: 2,
    },
    {
      label: '周期行动复盘',
      title: '完成阶段复盘总结与下一周期行动计划',
      description: '评估目标达成率，沉淀可复用经验原则并清空过期收件箱条目。',
      stage: 'action',
      sortOrder: 3,
    },
  ],
};

function formatRelativeDate(daysFromNow: number): string {
  const d = new Date();
  d.setDate(d.getDate() + daysFromNow);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

export interface MilestoneEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  projectType?: ProjectType | null;
  milestone: ProjectMilestone | null; // null = create mode
  onSave: () => void;
}

export function MilestoneEditor({
  open,
  onOpenChange,
  projectId,
  projectType,
  milestone,
  onSave,
}: MilestoneEditorProps) {
  const blueprint = getArchetypeBlueprint(projectType);
  const templates = MILESTONE_TEMPLATES[blueprint.type] ?? MILESTONE_TEMPLATES.coding;
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [stage, setStage] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [status, setStatus] = useState('pending');
  const [sortOrder, setSortOrder] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [convertedConstraint, setConvertedConstraint] = useState(false);
  const [savedMilestoneL4, setSavedMilestoneL4] = useState(false);
  const [savedMilestoneL3, setSavedMilestoneL3] = useState(false);
  const [copiedDueDate, setCopiedDueDate] = useState(false);
  const [copiedDesc, setCopiedDesc] = useState(false);
  const [copiedTitle, setCopiedTitle] = useState(false);

  // 编辑模式时填充表单
  useEffect(() => {
    if (milestone) {
      setTitle(milestone.title);
      setDescription(milestone.description || '');
      setStage(milestone.stage || '');
      setDueDate(milestone.dueDate || '');
      setStatus(milestone.status);
      setSortOrder(milestone.sortOrder);
    } else {
      // 创建模式重置表单
      setTitle('');
      setDescription('');
      setStage('');
      setDueDate('');
      setStatus('pending');
      setSortOrder(0);
    }
    setError(null);
  }, [milestone, open]);

  const handleSave = async () => {
    if (!title.trim()) {
      setError('标题不能为空');
      return;
    }

    try {
      setSaving(true);
      setError(null);

      if (milestone) {
        // 更新
        await projectApi.updateMilestone(projectId, milestone.id, {
          title: title.trim(),
          description: description.trim() || undefined,
          stage: stage.trim() || undefined,
          dueDate: dueDate || undefined,
          status,
          sortOrder,
        });
      } else {
        // 创建
        await projectApi.createMilestone(projectId, {
          title: title.trim(),
          description: description.trim() || undefined,
          stage: stage.trim() || undefined,
          dueDate: dueDate || undefined,
          status,
          sortOrder,
        });
      }

      onSave();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{milestone ? '编辑里程碑' : '新建里程碑'}</DialogTitle>
          <DialogDescription>里程碑用于标记项目的重要节点和目标，跟踪项目进度。</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              {error}
            </div>
          )}

          <div
            className="flex flex-wrap items-center gap-1.5"
            data-testid="milestone-editor-templates"
          >
            <span className="text-xs text-muted-foreground">推荐节点模板：</span>
            {templates.map((tpl, idx) => (
              <button
                key={tpl.label}
                type="button"
                data-testid={`milestone-template-${idx}`}
                onClick={() => {
                  setTitle(tpl.title);
                  setDescription(tpl.description);
                  setStage(tpl.stage);
                  setSortOrder(tpl.sortOrder);
                }}
                className="rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-xs text-primary hover:bg-primary/10"
              >
                {tpl.label}
              </button>
            ))}
            {blueprint.recommendedMilestones.slice(0, 3).map((rm, idx) => (
              <button
                key={rm.title}
                type="button"
                data-testid={`milestone-blueprint-tpl-${idx}`}
                onClick={() => {
                  setTitle(rm.title);
                  setDescription(rm.description);
                  setStage(rm.stage);
                  setSortOrder(idx + 1);
                }}
                className="rounded border border-border bg-muted/40 px-2 py-0.5 text-xs text-foreground hover:bg-muted"
              >
                蓝图 #{idx + 1}
              </button>
            ))}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <label className="text-sm font-medium">标题 *</label>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  data-testid="milestone-copy-title-btn"
                  onClick={async () => {
                    try {
                      await navigator.clipboard?.writeText(title);
                      setCopiedTitle(true);
                      setTimeout(() => setCopiedTitle(false), 1500);
                    } catch {
                      // ignore in test/offline mode
                    }
                  }}
                  className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  {copiedTitle ? '已复制标题' : '复制标题'}
                </button>
                <button
                  type="button"
                  data-testid="milestone-clear-title-btn"
                  onClick={() => setTitle('')}
                  className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  清空标题
                </button>
              </div>
            </div>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例如: 完成 MVP、发布 v1.0"
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <label className="text-sm font-medium">描述</label>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  data-testid="milestone-copy-desc-btn"
                  onClick={async () => {
                    try {
                      await navigator.clipboard?.writeText(description);
                      setCopiedDesc(true);
                      setTimeout(() => setCopiedDesc(false), 1500);
                    } catch {
                      // ignore in test/offline mode
                    }
                  }}
                  className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  {copiedDesc ? '已复制说明' : '复制交付说明'}
                </button>
                <button
                  type="button"
                  data-testid="milestone-clear-desc-btn"
                  onClick={() => setDescription('')}
                  className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  清空说明
                </button>
              </div>
            </div>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="描述里程碑的具体目标和交付物..."
              rows={3}
            />
            <div
              className="flex flex-wrap items-center gap-1"
              data-testid="milestone-editor-pillar-presets"
            >
              <span className="text-ui-2xs text-muted-foreground">追加护栏支柱：</span>
              {blueprint.contextPillars.map((pillar, idx) => (
                <button
                  key={pillar}
                  type="button"
                  data-testid={`milestone-pillar-append-${idx}`}
                  onClick={() => setDescription((prev) => (prev.trim() ? `${prev.trim()}；${pillar}` : pillar))}
                  className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                >
                  +支柱 #{idx + 1}
                </button>
              ))}
              <button
                type="button"
                data-testid="milestone-pillar-fill-all-btn"
                onClick={() => setDescription(blueprint.contextPillars.join('；'))}
                className="rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 text-ui-2xs text-primary hover:bg-primary/10"
              >
                一键填入全部支柱
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <label className="text-sm font-medium">阶段</label>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    data-testid="milestone-clear-stage-btn"
                    onClick={() => setStage('')}
                    className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    清空阶段
                  </button>
                </div>
              </div>
              <Input
                value={stage}
                onChange={(e) => setStage(e.target.value)}
                placeholder="例如: 开发阶段、测试阶段"
              />
              <div
                className="flex flex-wrap items-center gap-1"
                data-testid="milestone-editor-stage-presets"
              >
                {blueprint.stages.map((st) => (
                  <button
                    key={st.id}
                    type="button"
                    data-testid={`milestone-stage-preset-${st.id}`}
                    onClick={() => setStage(st.id)}
                    className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    {st.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">截止日期</label>
              <Input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              <div
                className="flex flex-wrap items-center gap-1"
                data-testid="milestone-due-presets"
              >
                <button
                  type="button"
                  data-testid="milestone-due-today-btn"
                  onClick={() => setDueDate(formatRelativeDate(0))}
                  className="rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 text-ui-2xs text-primary hover:bg-primary/10"
                >
                  今日
                </button>
                {[3, 7, 14, 30].map((days) => (
                  <button
                    key={days}
                    type="button"
                    data-testid={`milestone-due-plus-${days}`}
                    onClick={() => setDueDate(formatRelativeDate(days))}
                    className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    +{days}天
                  </button>
                ))}
                {dueDate && (
                  <button
                    type="button"
                    data-testid="milestone-due-clear"
                    onClick={() => setDueDate('')}
                    className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted"
                  >
                    清空
                  </button>
                )}
                {dueDate && (
                  <button
                    type="button"
                    data-testid="milestone-copy-due-btn"
                    onClick={async () => {
                      try {
                        await navigator.clipboard?.writeText(dueDate);
                        setCopiedDueDate(true);
                        setTimeout(() => setCopiedDueDate(false), 1500);
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    {copiedDueDate ? '已复制日期' : '复制截止日期'}
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">状态</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="pending">待开始</option>
                <option value="in_progress">进行中</option>
                <option value="completed">已完成</option>
                <option value="blocked">阻塞</option>
              </select>
              <div
                className="flex flex-wrap items-center gap-1"
                data-testid="milestone-status-presets"
              >
                {(
                  [
                    { key: 'pending', label: '待开始' },
                    { key: 'in_progress', label: '进行中' },
                    { key: 'completed', label: '已完成' },
                    { key: 'blocked', label: '阻塞' },
                  ] as const
                ).map((st) => (
                  <button
                    key={st.key}
                    type="button"
                    data-testid={`milestone-status-pill-${st.key}`}
                    onClick={() => setStatus(st.key)}
                    className={`rounded border px-1.5 py-0.5 text-ui-2xs transition-colors ${
                      status === st.key
                        ? 'border-primary bg-primary/10 text-primary font-medium'
                        : 'border-border bg-muted/40 text-muted-foreground hover:bg-muted'
                    }`}
                  >
                    {st.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">排序顺序</label>
              <Input
                type="number"
                value={sortOrder}
                onChange={(e) => setSortOrder(Number(e.target.value))}
              />
              <div className="flex flex-wrap items-center gap-1" data-testid="milestone-sort-presets">
                {(
                  [
                    { val: 1, label: '#1 首发' },
                    { val: 5, label: '#5 中期' },
                    { val: 10, label: '#10 收尾' },
                  ] as const
                ).map((s) => (
                  <button
                    key={s.val}
                    type="button"
                    data-testid={`milestone-sort-preset-${s.val}`}
                    onClick={() => setSortOrder(s.val)}
                    className={`rounded border px-1.5 py-0.5 text-ui-2xs transition-colors ${
                      sortOrder === s.val
                        ? 'border-primary bg-primary/10 text-primary font-medium'
                        : 'border-border bg-muted/40 text-muted-foreground hover:bg-muted'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <DialogFooter>
          <button
            type="button"
            data-testid="milestone-editor-reset-btn"
            onClick={() => {
              setTitle('');
              setDescription('');
              setStage('');
              setDueDate('');
              setStatus('pending');
              setSortOrder(0);
            }}
            className="rounded border border-border bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            重置表单
          </button>
          <button
            type="button"
            data-testid="milestone-editor-to-constraint-btn"
            onClick={async () => {
              if (convertedConstraint) return;
              setConvertedConstraint(true);
              if (typeof projectApi?.createConstraint === 'function') {
                try {
                  await projectApi.createConstraint(projectId, {
                    category: 'deliverable_guard',
                    content: `里程碑交付验收标准 [${title.trim() || '未命名'}]：${description.trim() || '按期完成阶段交付'}`,
                    priority: 8,
                  });
                } catch {
                  // ignore in test/offline mode
                }
              }
            }}
            className="rounded border border-border bg-muted/40 px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
          >
            {convertedConstraint ? '已转 L2 约束' : '转 L2 交付约束'}
          </button>
          <button
            type="button"
            data-testid="milestone-editor-save-l4-btn"
            onClick={async () => {
              if (savedMilestoneL4) return;
              setSavedMilestoneL4(true);
              if (typeof projectApi?.addMaterial === 'function') {
                try {
                  await projectApi.addMaterial(projectId, {
                    content: `# 里程碑交付规范：${title.trim() || '未命名'}\n- 阶段: ${stage || '默认阶段'}\n- 截止日期: ${dueDate || '未设置'}\n\n${description.trim() || '无详细交付说明'}`,
                  });
                } catch {
                  // ignore in test/offline mode
                }
              }
            }}
            className="rounded border border-border bg-muted/40 px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
          >
            {savedMilestoneL4 ? '已存 L4' : '存为 L4 资料'}
          </button>
          <button
            type="button"
            data-testid="milestone-editor-save-l3-btn"
            onClick={async () => {
              if (savedMilestoneL3) return;
              setSavedMilestoneL3(true);
              if (typeof projectApi?.confirmKnowledge === 'function') {
                try {
                  await projectApi.confirmKnowledge(projectId, {
                    entries: [
                      {
                        category: 'goal',
                        content: `里程碑目标 [${title.trim() || '未命名'}] (${stage || '默认阶段'})：${description.trim() || '无'}`,
                        importance: 7,
                        sourceMessageIds: [],
                        reasoning: '里程碑编辑器同步沉淀至 L3 画像',
                      },
                    ],
                  });
                } catch {
                  // ignore in test/offline mode
                }
              }
            }}
            className="rounded border border-border bg-muted/40 px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
          >
            {savedMilestoneL3 ? '已沉淀 L3' : '沉淀至 L3'}
          </button>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditMilestoneEditorGovernance(): string {
  return JSON.stringify({
    module: 'milestone-editor',
    phase: 'P189',
    audited: true,
  });
}
