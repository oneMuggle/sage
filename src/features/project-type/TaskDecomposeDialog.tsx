/**
 * AI 任务分解对话框 (M1, 2026-10-12 / Phase P23 形态预设与 M3→M1 预填联动)
 *
 * 用户在里程碑管理页点击「AI 任务分解」或在 AI 顾问卡片点击「分解为任务」打开此对话框。
 * 流程：
 * 1. 输入需求描述（必填，支持四形态快捷需求预设与 M3 建议自动预填）+ 补充上下文（可选）
 * 2. 点击「生成方案」→ 调用 LLM 预览
 * 3. 展示里程碑树预览（自动映射中文阶段名称）
 * 4. 用户确认后点击「采纳」→ 批量创建里程碑
 */

import { Sparkles, Loader2, ChevronRight, ChevronDown, CheckCircle2, Copy, Check } from 'lucide-react';
import { useState, useCallback, useEffect } from 'react';

import { projectApi, type PreviewMilestoneNode, type ProjectType } from '../../shared/api';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../../shared/ui/Dialog/Dialog';
import { Textarea } from '../../shared/ui/Textarea';

import { getArchetypeBlueprint } from './archetypeBlueprints';

interface DecomposePreset {
  label: string;
  requirement: string;
  context: string;
}

const DECOMPOSE_PRESETS_BY_TYPE: Record<ProjectType, DecomposePreset[]> = {
  coding: [
    {
      label: '模块重构与测试加固',
      requirement: '梳理核心模块接口边界，完成服务层解耦重构并补充端到端回归测试与 CI 门禁验证。',
      context: '遵循单文件 <= 800 行架构红线与 IPC 契约一致性规范。',
    },
    {
      label: '新特性全链路交付',
      requirement: '完成新特性从后端 Schema/API 设计、IPC 桥接路由到前端交互组件与单元测试的全链路交付。',
      context: '需同步通过 TypeScript 类型检查、ESLint 与 Ruff 静态门禁。',
    },
  ],
  business: [
    {
      label: '重大合同起草与会签归档',
      requirement: '完成年度采购/合作合同背景资料归集、初稿起草、法务合规与大小写金额双轨核验及签发封卷。',
      context: '遵循四级立卷目录规范，定稿签发前固化内置版本快照。',
    },
    {
      label: '专项请示公文与汇报编制',
      requirement: '归集政策依据与业务数据台账，按 GB/T 9704 公文版式完成专项请示工作稿与审校定稿。',
      context: '引用条款须注明原始依据来源，严禁主观臆造数据。',
    },
  ],
  research: [
    {
      label: '课题开题至论文投稿全流程',
      requirement: '完成核心文献综述与 Citation Key 建库、基线模型复现、消融对比实验与论文手稿撰写审校。',
      context: '严格执行零幻觉文献引用铁律，所有主实验须固定随机种子并记录超参数。',
    },
    {
      label: '审稿意见逐条回复与修回',
      requirement: '拆解审稿人质疑点，补充验证实验与统计显著性分析，完成 Response Letter 与正文中修回高亮。',
      context: '每条回复须绑定新增实验图表或已入库文献依据。',
    },
  ],
  personal: [
    {
      label: '主题知识图谱与卡片盒构建',
      requirement: '整理收件箱阅读摘录，提炼原子化永久笔记卡片并建立跨领域 [[双链概念]] 索引与专题综述。',
      context: '采用 Zettelkasten 卡片盒方法，每周输出可执行下一步行动项 (Next Actions)。',
    },
    {
      label: '季度复盘与目标行动拆解',
      requirement: '盘点本季度核心知识产出与待办完成度，拆解下一阶段学习研究计划与关键交付节点。',
      context: '按周设定可量化里程碑检查点。',
    },
  ],
};

export interface TaskDecomposeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  projectType?: ProjectType | null;
  initialRequirement?: string;
  initialContext?: string;
  /** 采纳后回调（外部重新拉取里程碑列表） */
  onApplied: () => void;
}

type Phase = 'input' | 'loading' | 'preview' | 'applying';

export function TaskDecomposeDialog({
  open,
  onOpenChange,
  projectId,
  projectType = 'coding',
  initialRequirement,
  initialContext,
  onApplied,
}: TaskDecomposeDialogProps) {
  const [phase, setPhase] = useState<Phase>('input');
  const [requirement, setRequirement] = useState('');
  const [context, setContext] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [reasoning, setReasoning] = useState('');
  const [milestones, setMilestones] = useState<PreviewMilestoneNode[]>([]);
  const [selectedRootIndices, setSelectedRootIndices] = useState<Set<number>>(new Set());
  const [copiedPlan, setCopiedPlan] = useState(false);
  const [savedReasoning, setSavedReasoning] = useState(false);
  const [stageFilter, setStageFilter] = useState<string>('all');
  const [savedPlanL4, setSavedPlanL4] = useState(false);
  const [constraintNodeIndices, setConstraintNodeIndices] = useState<Set<number>>(new Set());
  const [l3NodeIndices, setL3NodeIndices] = useState<Set<number>>(new Set());
  const [l4NodeIndices, setL4NodeIndices] = useState<Set<number>>(new Set());
  const [batchConvertedL2, setBatchConvertedL2] = useState(false);
  const [totalCount, setTotalCount] = useState(0);

  const effectiveType: ProjectType = projectType ?? 'coding';
  const blueprint = getArchetypeBlueprint(effectiveType);
  const presets = DECOMPOSE_PRESETS_BY_TYPE[effectiveType] ?? DECOMPOSE_PRESETS_BY_TYPE.coding;
  const stageLabelMap = new Map(blueprint.stages.map((s) => [s.id, s.label]));

  useEffect(() => {
    if (open) {
      if (initialRequirement !== undefined) setRequirement(initialRequirement);
      if (initialContext !== undefined) setContext(initialContext);
    }
  }, [open, initialRequirement, initialContext]);

  const handlePreview = useCallback(async () => {
    if (!requirement.trim() || typeof projectApi?.decomposePreview !== 'function') return;
    setError(null);
    setPhase('loading');
    try {
      const result = await projectApi.decomposePreview(projectId, {
        requirement: requirement.trim(),
        context: context.trim() || undefined,
      });
      setReasoning(result.reasoning);
      setMilestones(result.milestones);
      setSelectedRootIndices(new Set(result.milestones.map((_, i) => i)));
      setTotalCount(result.totalCount);
      setPhase('preview');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 分解失败');
      setPhase('input');
    }
  }, [projectId, requirement, context]);

  const resetAndClose = useCallback(() => {
    setPhase('input');
    setRequirement('');
    setContext('');
    setError(null);
    setReasoning('');
    setMilestones([]);
    setSelectedRootIndices(new Set());
    setTotalCount(0);
    onOpenChange(false);
  }, [onOpenChange]);

  const handleApply = useCallback(async () => {
    if (typeof projectApi?.decomposeApply !== 'function') return;
    setError(null);
    setPhase('applying');
    try {
      const chosen = milestones.filter((_, idx) => selectedRootIndices.has(idx));
      await projectApi.decomposeApply(projectId, { milestones: chosen.length > 0 ? chosen : milestones });
      onApplied();
      resetAndClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建里程碑失败');
      setPhase('preview');
    }
  }, [projectId, milestones, selectedRootIndices, onApplied, resetAndClose]);

  const handleCopyPreviewMarkdown = () => {
    const lines = [
      `# ${blueprint.label} · AI 任务拆解方案`,
      `- **需求**: ${requirement.trim()}`,
      reasoning ? `- **分解思路**: ${reasoning}` : '',
      '',
      '## 里程碑树',
    ].filter(Boolean);
    const walk = (nodes: PreviewMilestoneNode[], depth: number) => {
      for (const n of nodes) {
        const indent = '  '.repeat(depth);
        const stg = n.stage ? ` [${stageLabelMap.get(n.stage) ?? n.stage}]` : '';
        const days = n.estimatedDays != null ? ` (${n.estimatedDays}天)` : '';
        lines.push(`${indent}- **${n.title}**${stg}${days}${n.description ? `：${n.description}` : ''}`);
        if (n.children?.length) walk(n.children, depth + 1);
      }
    };
    walk(milestones, 0);
    try {
      void navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedPlan(true);
      setTimeout(() => setCopiedPlan(false), 1800);
    } catch {
      // ignore clipboard errors in test/offline mode
    }
  };

  return (
    <Dialog open={open} onOpenChange={resetAndClose}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            AI 智能任务分解
          </DialogTitle>
          <DialogDescription>
            描述你的需求（或点击下方「{blueprint.label}」快捷模板），AI 将结合项目阶段自动拆解为里程碑树
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              {error}
            </div>
          )}

          {/* 输入阶段 */}
          {(phase === 'input' || phase === 'loading') && (
            <>
              <div
                className="flex flex-wrap items-center gap-1.5"
                data-testid="decompose-archetype-presets"
              >
                <span className="text-ui-2xs text-muted-foreground">
                  {blueprint.label}推荐拆解模板：
                </span>
                {presets.map((preset, idx) => (
                  <button
                    key={preset.label}
                    type="button"
                    disabled={phase === 'loading'}
                    data-testid={`decompose-preset-${idx}`}
                    onClick={() => {
                      setRequirement(preset.requirement);
                      setContext(preset.context);
                    }}
                    className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-ui-2xs text-primary hover:bg-primary/10 disabled:opacity-50"
                  >
                    <Sparkles className="h-2.5 w-2.5" />
                    {preset.label}
                  </button>
                ))}
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  需求描述 <span className="text-red-500">*</span>
                </label>
                <Textarea
                  placeholder="例如：实现用户认证系统，包括注册、登录、JWT token 管理..."
                  value={requirement}
                  onChange={(e) => setRequirement(e.target.value)}
                  rows={4}
                  disabled={phase === 'loading'}
                  data-testid="decompose-requirement-input"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">补充上下文（可选）</label>
                <Textarea
                  placeholder="例如：使用 NextAuth.js，数据库用 PostgreSQL..."
                  value={context}
                  onChange={(e) => setContext(e.target.value)}
                  rows={2}
                  disabled={phase === 'loading'}
                  data-testid="decompose-context-input"
                />
              </div>
            </>
          )}

          {/* 预览阶段 */}
          {phase === 'preview' && (
            <div className="space-y-3">
              {reasoning && (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/50 p-3 text-sm text-muted-foreground">
                  <div>
                    <span className="font-medium text-foreground">分解思路：</span> {reasoning}
                  </div>
                  <button
                    type="button"
                    data-testid="decompose-save-reasoning-profile-btn"
                    disabled={savedReasoning}
                    onClick={async () => {
                      if (savedReasoning) return;
                      setSavedReasoning(true);
                      if (typeof projectApi?.confirmKnowledge === 'function') {
                        try {
                          await projectApi.confirmKnowledge(projectId, {
                            entries: [
                              {
                                category: 'decision',
                                content: `任务分解规划：${reasoning}`,
                                importance: 8,
                                sourceMessageIds: [],
                                reasoning: 'M3 任务分解思路沉淀',
                              },
                            ],
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="shrink-0 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:opacity-60"
                  >
                    {savedReasoning ? '已沉淀至 L3' : '沉淀思路至 L3 画像'}
                  </button>
                </div>
              )}
              <div className="space-y-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                    <span>
                      将创建 {totalCount} 个里程碑（已勾选 {selectedRootIndices.size}/{milestones.length} 个主节点）
                    </span>
                    <span
                      className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-normal text-primary"
                      data-testid="decompose-total-days-badge"
                    >
                      预计总工期{' '}
                      {milestones
                        .filter((_, idx) => selectedRootIndices.has(idx))
                        .reduce((acc, n) => acc + (n.estimatedDays ?? 0), 0)}{' '}
                      天
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <button
                      type="button"
                      data-testid="decompose-select-all-btn"
                      onClick={() => setSelectedRootIndices(new Set(milestones.map((_, i) => i)))}
                      className="rounded border border-border bg-background px-2 py-0.5 text-xs text-foreground hover:bg-muted"
                    >
                      全选
                    </button>
                    <button
                      type="button"
                      data-testid="decompose-select-invert-btn"
                      onClick={() =>
                        setSelectedRootIndices((prev) => {
                          const next = new Set<number>();
                          milestones.forEach((_, i) => {
                            if (!prev.has(i)) next.add(i);
                          });
                          return next;
                        })
                      }
                      className="rounded border border-border bg-background px-2 py-0.5 text-xs text-foreground hover:bg-muted"
                    >
                      反选
                    </button>
                    <button
                      type="button"
                      data-testid="decompose-batch-to-constraint-btn"
                      onClick={async () => {
                        if (batchConvertedL2) return;
                        setBatchConvertedL2(true);
                        const chosen = milestones.filter((_, idx) => selectedRootIndices.has(idx));
                        const list = chosen.length > 0 ? chosen : milestones;
                        if (typeof projectApi?.createConstraint === 'function') {
                          for (const node of list) {
                            try {
                              await projectApi.createConstraint(projectId, {
                                category: 'deliverable_guard',
                                content: `分解任务准入规范 [${node.title}]：${node.description || '按期完成分解节点交付'}`,
                                priority: 7,
                              });
                            } catch {
                              // ignore in test/offline mode
                            }
                          }
                        }
                      }}
                      className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-xs text-foreground hover:bg-muted"
                    >
                      {batchConvertedL2 ? '已转 L2 约束' : '选中转 L2 约束'}
                    </button>
                    <button
                      type="button"
                      data-testid="decompose-save-plan-l4-btn"
                      onClick={async () => {
                        if (savedPlanL4) return;
                        setSavedPlanL4(true);
                        if (typeof projectApi?.addMaterial === 'function') {
                          try {
                            await projectApi.addMaterial(projectId, {
                              content: `# 任务分解方案：${requirement.trim()}\n\n${reasoning}\n\n${milestones.map((m) => `- ${m.title} (${m.estimatedDays ?? 1}天)`).join('\n')}`,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-xs text-foreground hover:bg-muted"
                    >
                      {savedPlanL4 ? '已存为 L4' : '方案存为 L4'}
                    </button>
                    <button
                      type="button"
                      data-testid="decompose-copy-md-btn"
                      onClick={handleCopyPreviewMarkdown}
                      className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-xs text-foreground hover:bg-muted"
                    >
                      {copiedPlan ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                      {copiedPlan ? '已复制方案' : '复制方案 Markdown'}
                    </button>
                  </div>
                </div>
                {milestones.some((m) => m.stage) && (
                  <div className="flex flex-wrap items-center gap-1" data-testid="decompose-stage-filter-bar">
                    <button
                      type="button"
                      data-testid="decompose-stage-filter-all"
                      onClick={() => setStageFilter('all')}
                      className={`rounded border px-2 py-0.5 text-ui-2xs ${
                        stageFilter === 'all'
                          ? 'border-primary bg-primary text-primary-foreground'
                          : 'border-border bg-background text-muted-foreground hover:bg-muted'
                      }`}
                    >
                      全部阶段 ({milestones.length})
                    </button>
                    {Array.from(new Set(milestones.map((m) => m.stage).filter(Boolean))).map((st) => (
                      <button
                        key={st}
                        type="button"
                        data-testid={`decompose-stage-filter-${st}`}
                        onClick={() => setStageFilter(st!)}
                        className={`rounded border px-2 py-0.5 text-ui-2xs ${
                          stageFilter === st
                            ? 'border-primary bg-primary text-primary-foreground'
                            : 'border-border bg-background text-muted-foreground hover:bg-muted'
                        }`}
                      >
                        {stageLabelMap.get(st!) ?? st}
                      </button>
                    ))}
                  </div>
                )}
                <div className="rounded-lg border p-3 space-y-1">
                  {milestones.map((ms, idx) =>
                    stageFilter !== 'all' && ms.stage !== stageFilter ? null : (
                    <div key={idx} className="flex items-start gap-2">
                      <input
                        type="checkbox"
                        checked={selectedRootIndices.has(idx)}
                        data-testid={`decompose-node-checkbox-${idx}`}
                        onChange={() =>
                          setSelectedRootIndices((prev) => {
                            const next = new Set(prev);
                            if (next.has(idx)) next.delete(idx);
                            else next.add(idx);
                            return next;
                          })
                        }
                        className="mt-2 h-3.5 w-3.5 rounded border-border"
                      />
                      <div className="flex-1 min-w-0">
                        <MilestoneTreeItem
                          node={ms}
                          depth={0}
                          stageLabelMap={stageLabelMap}
                        />
                      </div>
                      <button
                        type="button"
                        data-testid={`decompose-node-to-constraint-${idx}`}
                        onClick={async () => {
                          if (constraintNodeIndices.has(idx)) return;
                          setConstraintNodeIndices((prev) => new Set(prev).add(idx));
                          if (typeof projectApi?.createConstraint === 'function') {
                            try {
                              await projectApi.createConstraint(projectId, {
                                category: 'deliverable_guard',
                                content: `分解任务验收规范 [${ms.title}]：${ms.description || '完成任务分解节点交付'}`,
                                priority: 7,
                              });
                            } catch {
                              // ignore in test/offline mode
                            }
                          }
                        }}
                        className="mt-1 shrink-0 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-primary hover:bg-primary/10"
                      >
                        {constraintNodeIndices.has(idx) ? '已转 L2' : '+L2 约束'}
                      </button>
                      <button
                        type="button"
                        data-testid={`decompose-node-to-l3-${idx}`}
                        onClick={async () => {
                          if (l3NodeIndices.has(idx)) return;
                          setL3NodeIndices((prev) => new Set(prev).add(idx));
                          if (typeof projectApi?.confirmKnowledge === 'function') {
                            try {
                              await projectApi.confirmKnowledge(projectId, {
                                entries: [
                                  {
                                    category: 'goal',
                                    content: `分解里程碑目标 [${ms.title}]：${ms.description || '阶段核心交付项'}`,
                                    importance: 7,
                                    sourceMessageIds: [],
                                    reasoning: 'M1 任务分解节点同步沉淀至 L3 画像',
                                  },
                                ],
                              });
                            } catch {
                              // ignore in test/offline mode
                            }
                          }
                        }}
                        className="mt-1 shrink-0 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        {l3NodeIndices.has(idx) ? '已存L3' : '+L3'}
                      </button>
                      <button
                        type="button"
                        data-testid={`decompose-node-to-l4-${idx}`}
                        onClick={async () => {
                          if (l4NodeIndices.has(idx)) return;
                          setL4NodeIndices((prev) => new Set(prev).add(idx));
                          if (typeof projectApi?.addMaterial === 'function') {
                            try {
                              await projectApi.addMaterial(projectId, {
                                content: `# 分解任务档案：${ms.title}\n- 阶段: ${ms.stage || '默认阶段'}\n\n${ms.description || '无详细说明'}`,
                              });
                            } catch {
                              // ignore in test/offline mode
                            }
                          }
                        }}
                        className="mt-1 shrink-0 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        {l4NodeIndices.has(idx) ? '已存L4' : '+L4'}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 应用中 */}
          {phase === 'applying' && (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在创建里程碑...
            </div>
          )}
        </div>

        <DialogFooter>
          {(phase === 'input' || phase === 'loading') && (
            <>
              <Button variant="secondary" onClick={resetAndClose}>
                取消
              </Button>
              <Button
                onClick={() => void handlePreview()}
                disabled={!requirement.trim() || phase === 'loading'}
                data-testid="decompose-preview-btn"
              >
                {phase === 'loading' ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    分析中...
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    生成方案
                  </>
                )}
              </Button>
            </>
          )}
          {phase === 'preview' && (
            <>
              <Button variant="secondary" onClick={() => setPhase('input')}>
                重新输入
              </Button>
              <Button onClick={() => void handleApply()} data-testid="decompose-apply-btn">
                <CheckCircle2 className="mr-2 h-4 w-4" />
                采纳方案
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 递归渲染里程碑树节点 */
function MilestoneTreeItem({
  node,
  depth,
  stageLabelMap,
}: {
  node: PreviewMilestoneNode;
  depth: number;
  stageLabelMap: Map<string, string>;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;

  return (
    <div style={{ paddingLeft: depth * 20 }}>
      <div className="flex items-start gap-1.5 py-1">
        {hasChildren ? (
          <button
            type="button"
            className="mt-0.5 shrink-0 rounded p-0.5 hover:bg-muted"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
          </button>
        ) : (
          <span className="w-5 shrink-0" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{node.title}</span>
            {node.estimatedDays != null && (
              <Badge variant="outline" className="text-xs">
                {node.estimatedDays}天
              </Badge>
            )}
            {node.stage && (
              <Badge variant="secondary" className="text-xs">
                {stageLabelMap.get(node.stage) ?? node.stage}
              </Badge>
            )}
          </div>
          {node.description && (
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{node.description}</p>
          )}
        </div>
      </div>
      {expanded && hasChildren && (
        <div>
          {node.children.map((child: PreviewMilestoneNode, idx: number) => (
            <MilestoneTreeItem
              key={idx}
              node={child}
              depth={depth + 1}
              stageLabelMap={stageLabelMap}
            />
          ))}
        </div>
      )}
    </div>
  );
}
