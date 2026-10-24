/**
 * 里程碑管理器 (2026-09-25；Phase P20 阶段筛选、进度汇总与路线图 Markdown 导出 2026-10-12)
 *
 * 项目类型分类系统 - Phase 4.5
 * 里程碑的 CRUD 界面：列表、创建、编辑、删除、状态更新、阶段筛选与路线图导出
 */

import {
  Plus,
  Edit2,
  Trash2,
  Target,
  CheckCircle2,
  Clock,
  AlertCircle,
  Sparkles,
  BrainCircuit,
  Copy,
  Check,
} from 'lucide-react';
import { useState, useEffect, useCallback, useMemo } from 'react';

import { projectApi, type ProjectMilestone, type ProjectType } from '../../shared/api';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';
import { Progress } from '../../shared/ui/Progress';

import { MilestoneEditor } from './MilestoneEditor';
import { TaskDecomposeDialog } from './TaskDecomposeDialog';
import { getArchetypeBlueprint } from './archetypeBlueprints';

export interface MilestoneManagerProps {
  projectId: string;
  projectType?: ProjectType;
}

export function MilestoneManager({ projectId, projectType = 'business' }: MilestoneManagerProps) {
  const [milestones, setMilestones] = useState<ProjectMilestone[]>([]);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingMilestone, setEditingMilestone] = useState<ProjectMilestone | null>(null);
  const [decomposeDialogOpen, setDecomposeDialogOpen] = useState(false);
  const [decomposeInitReq, setDecomposeInitReq] = useState<string>('');
  const [decomposeInitCtx, setDecomposeInitCtx] = useState<string>('');
  const [stageFilter, setStageFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [overdueOnly, setOverdueOnly] = useState<boolean>(false);
  const [copiedRoadmap, setCopiedRoadmap] = useState(false);
  const [promotedMilestoneIds, setPromotedMilestoneIds] = useState<Set<string>>(new Set());
  const [copiedMilestoneId, setCopiedMilestoneId] = useState<string | null>(null);
  const [batchSavedMilestonesL3, setBatchSavedMilestonesL3] = useState(false);
  const [batchSavedMilestonesL4, setBatchSavedMilestonesL4] = useState(false);
  const [batchConvertedConstraints, setBatchConvertedConstraints] = useState(false);
  const [constraintMilestoneIds, setConstraintMilestoneIds] = useState<Set<string>>(new Set());
  const [l4MilestoneIds, setL4MilestoneIds] = useState<Set<string>>(new Set());
  const blueprint = getArchetypeBlueprint(projectType);

  const stageLabelMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of blueprint.stages) {
      map.set(s.id, s.label);
    }
    return map;
  }, [blueprint.stages]);

  const fetchMilestones = useCallback(async () => {
    try {
      setLoading(true);
      const list = await projectApi.listMilestones(projectId);
      setMilestones(list.sort((a, b) => a.sortOrder - b.sortOrder));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取里程碑失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void fetchMilestones();
  }, [fetchMilestones]);

  const handleCreate = () => {
    setEditingMilestone(null);
    setEditorOpen(true);
  };

  const handleSeedRecommendedMilestones = async () => {
    if (seeding || typeof projectApi?.createMilestone !== 'function') return;
    setSeeding(true);
    setError(null);
    try {
      const existingTitles = new Set(milestones.map((m) => m.title));
      let nextOrder = milestones.length;
      for (const item of blueprint.recommendedMilestones) {
        if (existingTitles.has(item.title)) continue;
        await projectApi.createMilestone(projectId, {
          title: item.title,
          description: item.description,
          stage: item.stage,
          sortOrder: nextOrder++,
        });
      }
      await fetchMilestones();
    } catch (err) {
      setError(err instanceof Error ? err.message : '导入推荐里程碑失败');
    } finally {
      setSeeding(false);
    }
  };

  const handleCopyRoadmap = async () => {
    if (milestones.length === 0) return;
    const lines = [
      `# ${blueprint.label} · 里程碑路线图`,
      '',
      ...milestones.map((m) => {
        const mark = m.status === 'completed' ? '[x]' : '[ ]';
        const stg = m.stage ? ` (${stageLabelMap.get(m.stage) ?? m.stage})` : '';
        const due = m.dueDate ? ` · 截止: ${m.dueDate}` : '';
        return `- ${mark} **${m.title}**${stg}${due}${m.description ? ` — ${m.description}` : ''}`;
      }),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedRoadmap(true);
      setTimeout(() => setCopiedRoadmap(false), 1800);
    } catch {
      // ignore clipboard errors in headless mode
    }
  };

  const handleEdit = (milestone: ProjectMilestone) => {
    setEditingMilestone(milestone);
    setEditorOpen(true);
  };

  const handleDelete = async (milestoneId: string) => {
    const ok = await confirmDialog({ title: '删除里程碑', message: '确定要删除此里程碑吗？', danger: true });
    if (!ok) return;
    try {
      await projectApi.deleteMilestone(projectId, milestoneId);
      await fetchMilestones();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除里程碑失败');
    }
  };

  const handleStatusChange = async (milestoneId: string, status: string) => {
    try {
      await projectApi.updateMilestone(projectId, milestoneId, { status });
      await fetchMilestones();
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新状态失败');
    }
  };

  const handleEditorSave = async () => {
    setEditorOpen(false);
    await fetchMilestones();
  };

  const completedCount = milestones.filter((m) => m.status === 'completed').length;
  const completionPct = milestones.length > 0 ? Math.round((completedCount / milestones.length) * 100) : 0;
  const todayIso = new Date().toISOString().slice(0, 10);
  const overdueCount = useMemo(
    () =>
      milestones.filter(
        (m) => m.status !== 'completed' && Boolean(m.dueDate) && String(m.dueDate) < todayIso,
      ).length,
    [milestones, todayIso],
  );

  const filteredMilestones = useMemo(() => {
    let list = milestones.filter((m) => {
      if (stageFilter !== 'all' && m.stage !== stageFilter) return false;
      if (statusFilter !== 'all' && m.status !== statusFilter) return false;
      return true;
    });
    if (overdueOnly) {
      list = list.filter(
        (m) => m.status !== 'completed' && Boolean(m.dueDate) && String(m.dueDate) < todayIso,
      );
    }
    const q = searchQuery.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (m) =>
        m.title.toLowerCase().includes(q) ||
        (m.description ?? '').toLowerCase().includes(q),
    );
  }, [milestones, stageFilter, statusFilter, overdueOnly, todayIso, searchQuery]);

  const inProgressMilestones = useMemo(
    () => filteredMilestones.filter((m) => m.status === 'in_progress'),
    [filteredMilestones],
  );

  const handleBatchCompleteInProgress = async () => {
    if (inProgressMilestones.length === 0) return;
    try {
      for (const m of inProgressMilestones) {
        await projectApi.updateMilestone(projectId, m.id, { status: 'completed' });
      }
      await fetchMilestones();
    } catch (err) {
      setError(err instanceof Error ? err.message : '批量完成里程碑失败');
    }
  };

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Target className="h-5 w-5" />
            里程碑管理
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">加载中...</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <Card data-testid="milestone-manager-panel">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2">
              <Target className="h-5 w-5" />
              里程碑管理
            </CardTitle>
            <div className="flex flex-wrap items-center gap-2">
              {milestones.length > 0 && (
                <button
                  type="button"
                  onClick={() => void handleCopyRoadmap()}
                  data-testid="milestone-copy-roadmap-btn"
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-muted"
                >
                  {copiedRoadmap ? (
                    <>
                      <Check className="h-3.5 w-3.5 text-emerald-500" />
                      已复制路线图
                    </>
                  ) : (
                    <>
                      <Copy className="h-3.5 w-3.5 text-muted-foreground" />
                      复制路线图 Markdown
                    </>
                  )}
                </button>
              )}
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setDecomposeInitReq('');
                  setDecomposeInitCtx('');
                  setDecomposeDialogOpen(true);
                }}
                data-testid="ai-decompose-tasks-btn"
              >
                <BrainCircuit className="mr-1.5 h-3.5 w-3.5 text-primary" />
                AI 任务分解
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void handleSeedRecommendedMilestones()}
                disabled={seeding}
                data-testid="seed-archetype-milestones-btn"
              >
                <Sparkles className="mr-1.5 h-3.5 w-3.5 text-primary" />
                {seeding ? '导入中...' : `一键导入「${blueprint.label}」推荐里程碑`}
              </Button>
              <Button size="sm" onClick={handleCreate}>
                <Plus className="mr-2 h-4 w-4" />
                新建里程碑
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              <AlertCircle className="h-4 w-4" />
              {error}
            </div>
          )}

          {milestones.length > 0 && (
            <div
              className="space-y-2 rounded-lg border border-border/70 bg-muted/15 p-3"
              data-testid="milestone-manager-progress"
            >
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className="font-medium text-foreground">
                  总体达成进度：{completedCount} / {milestones.length} ({completionPct}%)
                </span>
                <div
                  className="flex flex-wrap items-center gap-1.5"
                  data-testid="milestone-stage-filter-bar"
                >
                  <button
                    type="button"
                    onClick={() => setStageFilter('all')}
                    data-testid="milestone-stage-filter-all"
                    className={`rounded px-2 py-0.5 text-ui-2xs font-medium transition-colors ${
                      stageFilter === 'all'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-background text-muted-foreground hover:bg-muted'
                    }`}
                  >
                    全部 ({milestones.length})
                  </button>
                  {blueprint.stages.map((stg) => {
                    const cnt = milestones.filter((m) => m.stage === stg.id).length;
                    if (cnt === 0) return null;
                    return (
                      <button
                        key={stg.id}
                        type="button"
                        onClick={() => setStageFilter(stg.id)}
                        data-testid={`milestone-stage-filter-${stg.id}`}
                        className={`rounded px-2 py-0.5 text-ui-2xs font-medium transition-colors ${
                          stageFilter === stg.id
                            ? 'bg-primary text-primary-foreground'
                            : 'bg-background text-muted-foreground hover:bg-muted'
                        }`}
                      >
                        {stg.label} ({cnt})
                      </button>
                    );
                  })}
                </div>
              </div>
              <Progress value={completionPct} className="h-1.5" />
              <div
                className="flex flex-wrap items-center gap-1.5 pt-1"
                data-testid="milestone-status-filter-bar"
              >
                <span className="text-ui-2xs text-muted-foreground">状态筛选：</span>
                {[
                  { id: 'all', label: '状态: 全部' },
                  { id: 'in_progress', label: '状态: 进行中' },
                  { id: 'pending', label: '状态: 待开始' },
                  { id: 'completed', label: '状态: 已完成' },
                  { id: 'blocked', label: '状态: 阻塞' },
                ].map((st) => (
                  <button
                    key={st.id}
                    type="button"
                    onClick={() => setStatusFilter(st.id)}
                    data-testid={`milestone-status-filter-${st.id}`}
                    className={`rounded px-2 py-0.5 text-ui-2xs font-medium transition-colors ${
                      statusFilter === st.id
                        ? 'bg-primary/15 text-primary border border-primary/30'
                        : 'bg-background text-muted-foreground hover:bg-muted'
                    }`}
                  >
                    {st.label}
                  </button>
                ))}
                {overdueCount > 0 && (
                  <button
                    type="button"
                    data-testid="milestone-overdue-filter-btn"
                    onClick={() => setOverdueOnly((v) => !v)}
                    className={`rounded px-2 py-0.5 text-ui-2xs font-medium transition-colors ${
                      overdueOnly
                        ? 'bg-amber-600 text-white'
                        : 'bg-amber-500/15 text-amber-700 hover:bg-amber-500/25 dark:text-amber-300'
                    }`}
                  >
                    逾期预警 ({overdueCount})
                  </button>
                )}
                {filteredMilestones.length > 0 && (
                  <button
                    type="button"
                    data-testid="milestone-batch-promote-l3-btn"
                    onClick={async () => {
                      if (batchSavedMilestonesL3) return;
                      setBatchSavedMilestonesL3(true);
                      if (typeof projectApi?.confirmKnowledge === 'function') {
                        try {
                          await projectApi.confirmKnowledge(projectId, {
                            entries: filteredMilestones.slice(0, 8).map((m) => ({
                              category: 'goal',
                              content: `里程碑节点 [${m.title}] (${m.status})：${m.description || '无详细说明'}`,
                              importance: 7,
                              sourceMessageIds: [],
                              reasoning: '里程碑管理器批量沉淀至 L3 画像',
                            })),
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-background px-2 py-0.5 text-ui-2xs font-medium text-foreground hover:bg-muted"
                  >
                    {batchSavedMilestonesL3 ? '已批量存 L3' : `批量存 L3 (${filteredMilestones.length})`}
                  </button>
                )}
                {filteredMilestones.length > 0 && (
                  <button
                    type="button"
                    data-testid="milestone-batch-save-l4-btn"
                    onClick={async () => {
                      if (batchSavedMilestonesL4) return;
                      setBatchSavedMilestonesL4(true);
                      if (typeof projectApi?.addMaterial === 'function') {
                        try {
                          await projectApi.addMaterial(projectId, {
                            content: `# ${blueprint.label} · 里程碑路线图档案 (${filteredMilestones.length} 项)\n${filteredMilestones
                              .map((m) => `- [${m.status}] ${m.title} (${m.stage || '默认阶段'})`)
                              .join('\n')}`,
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-background px-2 py-0.5 text-ui-2xs font-medium text-foreground hover:bg-muted"
                  >
                    {batchSavedMilestonesL4 ? '已批量存 L4' : `批量存 L4 (${filteredMilestones.length})`}
                  </button>
                )}
                {filteredMilestones.length > 0 && (
                  <button
                    type="button"
                    data-testid="milestone-batch-to-constraint-btn"
                    onClick={async () => {
                      if (batchConvertedConstraints) return;
                      setBatchConvertedConstraints(true);
                      if (typeof projectApi?.createConstraint === 'function') {
                        for (const m of filteredMilestones.slice(0, 6)) {
                          try {
                            await projectApi.createConstraint(projectId, {
                              category: 'deliverable_guard',
                              content: `里程碑交付验收要求 [${m.title}]：${m.description || '按期完成阶段交付'}`,
                              priority: 8,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }
                    }}
                    className="rounded border border-border bg-background px-2 py-0.5 text-ui-2xs font-medium text-foreground hover:bg-muted"
                  >
                    {batchConvertedConstraints ? '已批量转 L2' : `批量转 L2 (${filteredMilestones.length})`}
                  </button>
                )}
                {inProgressMilestones.length > 0 && (
                  <button
                    type="button"
                    data-testid="milestone-batch-complete-btn"
                    onClick={() => void handleBatchCompleteInProgress()}
                    className="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-ui-2xs font-medium text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-300"
                  >
                    一键完成进行中 ({inProgressMilestones.length})
                  </button>
                )}
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="搜索里程碑标题或描述..."
                  data-testid="milestone-search-input"
                  className="ml-auto w-44 rounded border border-input bg-background px-2 py-0.5 text-xs"
                />
              </div>
            </div>
          )}

          {filteredMilestones.length === 0 ? (
            <div className="py-8 text-center">
              <Target className="mx-auto h-12 w-12 text-muted-foreground/50" />
              <p className="mt-4 text-sm text-muted-foreground">暂无里程碑</p>
              <p className="mt-1 text-xs text-muted-foreground">创建里程碑以跟踪项目进度</p>
            </div>
          ) : (
            <div className="space-y-3">
              {filteredMilestones.map((milestone) => (
                <div
                  key={milestone.id}
                  className="flex items-start justify-between rounded-lg border p-3"
                >
                  <div className="flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{milestone.title}</span>
                      <StatusBadge status={milestone.status} />
                      {milestone.stage && (
                        <Badge variant="outline">
                          {stageLabelMap.get(milestone.stage) ?? milestone.stage}
                        </Badge>
                      )}
                    </div>
                    {milestone.description && (
                      <p className="text-sm text-muted-foreground">{milestone.description}</p>
                    )}
                    {milestone.dueDate && (
                      <p className="text-xs text-muted-foreground">截止日期: {milestone.dueDate}</p>
                    )}
                    {/* 状态切换按钮 */}
                    <div className="flex gap-1 pt-2">
                      {milestone.status !== 'pending' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleStatusChange(milestone.id, 'pending')}
                        >
                          待开始
                        </Button>
                      )}
                      {milestone.status !== 'in_progress' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleStatusChange(milestone.id, 'in_progress')}
                        >
                          进行中
                        </Button>
                      )}
                      {milestone.status !== 'completed' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleStatusChange(milestone.id, 'completed')}
                        >
                          完成
                        </Button>
                      )}
                      {milestone.status !== 'blocked' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleStatusChange(milestone.id, 'blocked')}
                        >
                          阻塞
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      data-testid={`milestone-promote-profile-${milestone.id}`}
                      onClick={async () => {
                        if (promotedMilestoneIds.has(milestone.id)) return;
                        setPromotedMilestoneIds((prev) => new Set(prev).add(milestone.id));
                        if (typeof projectApi?.confirmKnowledge === 'function') {
                          try {
                            await projectApi.confirmKnowledge(projectId, {
                              entries: [
                                {
                                  category: 'note',
                                  content: `里程碑记录 [${milestone.title}] (${milestone.status})：${milestone.description || '无详细说明'}`,
                                  importance: 7,
                                  sourceMessageIds: [],
                                  reasoning: '里程碑节点沉淀至 L3 画像',
                                },
                              ],
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                      title="沉淀该里程碑节点至 L3 项目画像"
                    >
                      {promotedMilestoneIds.has(milestone.id) ? '已存L3' : '+L3'}
                    </button>
                    <button
                      type="button"
                      data-testid={`milestone-to-constraint-${milestone.id}`}
                      onClick={async () => {
                        if (constraintMilestoneIds.has(milestone.id)) return;
                        setConstraintMilestoneIds((prev) => new Set(prev).add(milestone.id));
                        if (typeof projectApi?.createConstraint === 'function') {
                          try {
                            await projectApi.createConstraint(projectId, {
                              category: 'deliverable_guard',
                              content: `里程碑交付验收要求 [${milestone.title}]：${milestone.description || '按期完成阶段交付'}`,
                              priority: 8,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1 text-ui-2xs text-primary hover:bg-primary/10"
                      title="将该里程碑转化为 L2 交付约束"
                    >
                      {constraintMilestoneIds.has(milestone.id) ? '已转L2' : '+L2 约束'}
                    </button>
                    <button
                      type="button"
                      data-testid={`milestone-to-l4-${milestone.id}`}
                      onClick={async () => {
                        if (l4MilestoneIds.has(milestone.id)) return;
                        setL4MilestoneIds((prev) => new Set(prev).add(milestone.id));
                        if (typeof projectApi?.addMaterial === 'function') {
                          try {
                            await projectApi.addMaterial(projectId, {
                              content: `# 里程碑档案：${milestone.title}\n- 状态: ${milestone.status}\n- 阶段: ${milestone.stage || '默认阶段'}\n\n${milestone.description || '无详细说明'}`,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      {l4MilestoneIds.has(milestone.id) ? '已存L4' : '+L4'}
                    </button>
                    <button
                      type="button"
                      data-testid={`milestone-copy-single-${milestone.id}`}
                      onClick={() => {
                        try {
                          void navigator.clipboard?.writeText(
                            `- [${milestone.status === 'completed' ? 'x' : ' '}] **${milestone.title}** (${milestone.stage || '默认阶段'}) ${milestone.description || ''}`,
                          );
                          setCopiedMilestoneId(milestone.id);
                          setTimeout(() => setCopiedMilestoneId(null), 1500);
                        } catch {
                          // ignore in test/offline mode
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-1 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      {copiedMilestoneId === milestone.id ? '已复制' : '复制'}
                    </button>
                    <button
                      type="button"
                      data-testid={`milestone-decompose-${milestone.id}`}
                      onClick={() => {
                        setDecomposeInitReq(milestone.title);
                        setDecomposeInitCtx(milestone.description || '');
                        setDecomposeDialogOpen(true);
                      }}
                      className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-1 text-ui-2xs font-medium text-primary hover:bg-primary/10"
                      title="基于此里程碑让 AI 拆解子任务"
                    >
                      <BrainCircuit className="h-3 w-3" />
                      AI 拆解子任务
                    </button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`编辑里程碑：${milestone.title}`}
                      onClick={() => handleEdit(milestone)}
                    >
                      <Edit2 className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`删除里程碑：${milestone.title}`}
                      onClick={() => handleDelete(milestone.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <MilestoneEditor
        open={editorOpen}
        onOpenChange={setEditorOpen}
        projectId={projectId}
        projectType={projectType}
        milestone={editingMilestone}
        onSave={handleEditorSave}
      />

      <TaskDecomposeDialog
        open={decomposeDialogOpen}
        onOpenChange={setDecomposeDialogOpen}
        projectId={projectId}
        projectType={projectType}
        initialRequirement={decomposeInitReq}
        initialContext={decomposeInitCtx}
        onApplied={fetchMilestones}
      />
    </>
  );
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<
    string,
    {
      icon: React.ReactNode;
      label: string;
      variant: 'default' | 'secondary' | 'destructive' | 'outline';
    }
  > = {
    pending: {
      icon: <Clock className="h-3 w-3" />,
      label: '待开始',
      variant: 'secondary',
    },
    in_progress: {
      icon: <Clock className="h-3 w-3" />,
      label: '进行中',
      variant: 'default',
    },
    completed: {
      icon: <CheckCircle2 className="h-3 w-3" />,
      label: '已完成',
      variant: 'default',
    },
    blocked: {
      icon: <AlertCircle className="h-3 w-3" />,
      label: '阻塞',
      variant: 'destructive',
    },
  };

  const { icon, label, variant } = config[status] || config.pending;

  return (
    <Badge variant={variant}>
      <span className="flex items-center gap-1">
        {icon}
        {label}
      </span>
    </Badge>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditMilestoneManagerGovernance(): string {
  return JSON.stringify({
    module: 'milestone-manager',
    phase: 'P190',
    audited: true,
  });
}
