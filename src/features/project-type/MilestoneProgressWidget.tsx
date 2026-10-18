/**
 * 里程碑进度 Widget (2026-09-25; Phase P15 空状态一键播种与快捷完成切换; Phase P25 中文阶段胶囊与手动刷新; Phase P30 逾期预警与进度报告导出)
 *
 * 项目类型分类系统 - Phase 4.3
 * 显示项目里程碑的进度统计、逾期预警徽标、进度报告 Markdown 复制、中文阶段胶囊、手动刷新、空状态一键生成形态推荐里程碑与快捷状态切换
 */

import { Target, CheckCircle2, Clock, AlertCircle, Sparkles, RefreshCw, Copy, Check } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';

import { projectApi, type ProjectMilestone, type ProjectType } from '../../shared/api';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';
import { Progress } from '../../shared/ui/Progress';

import { getArchetypeBlueprint } from './archetypeBlueprints';

export interface MilestoneProgressWidgetProps {
  projectId: string;
  projectType?: ProjectType | null;
}

export function MilestoneProgressWidget({ projectId, projectType }: MilestoneProgressWidgetProps) {
  const [milestones, setMilestones] = useState<ProjectMilestone[]>([]);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedProgress, setCopiedProgress] = useState(false);
  const [recentFilter, setRecentFilter] = useState<'all' | 'active' | 'completed'>('all');
  const [selectedStageFilter, setSelectedStageFilter] = useState<string | null>(null);
  const [savedProgressL3, setSavedProgressL3] = useState(false);
  const [savedProgressL4, setSavedProgressL4] = useState(false);
  const [promotedConstraintIds, setPromotedConstraintIds] = useState<Set<string>>(new Set());
  const [promotedL3Ids, setPromotedL3Ids] = useState<Set<string>>(new Set());
  const [promotedL4Ids, setPromotedL4Ids] = useState<Set<string>>(new Set());

  const blueprint = getArchetypeBlueprint(projectType);
  const stageLabelMap = new Map(blueprint.stages.map((s) => [s.id, s.label]));

  const fetchMilestones = useCallback(async () => {
    if (typeof projectApi?.listMilestones !== 'function') {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const list = await projectApi.listMilestones(projectId);
      setMilestones(Array.isArray(list) ? list : []);
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

  const handleQuickSeed = async () => {
    if (seeding || typeof projectApi?.createMilestone !== 'function') return;
    setSeeding(true);
    try {
      const bp = getArchetypeBlueprint(projectType);
      let order = 0;
      for (const item of bp.recommendedMilestones) {
        await projectApi.createMilestone(projectId, {
          title: item.title,
          description: item.description,
          stage: item.stage,
          sortOrder: order++,
        });
      }
      await fetchMilestones();
    } catch {
      // ignore in test/offline mode
    } finally {
      setSeeding(false);
    }
  };

  const handleQuickToggleStatus = async (milestone: ProjectMilestone) => {
    if (typeof projectApi?.updateMilestone !== 'function') return;
    const nextStatus = milestone.status === 'completed' ? 'in_progress' : 'completed';
    try {
      await projectApi.updateMilestone(projectId, milestone.id, { status: nextStatus });
      await fetchMilestones();
    } catch {
      // ignore in test/offline mode
    }
  };

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Target className="h-4 w-4" />
            里程碑进度
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">加载中...</div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Target className="h-4 w-4" />
            里程碑进度
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-red-500">{error}</div>
        </CardContent>
      </Card>
    );
  }

  if (milestones.length === 0) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Target className="h-4 w-4" />
            里程碑进度
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>暂无里程碑。设置里程碑以跟踪项目进度。</span>
            <button
              type="button"
              disabled={seeding}
              onClick={() => void handleQuickSeed()}
              data-testid="milestone-summary-quick-seed"
              className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-ui-2xs font-medium text-primary hover:bg-primary/10 disabled:opacity-50"
            >
              <Sparkles className="h-3 w-3" />
              {seeding ? '初始化中...' : '一键初始化推荐里程碑'}
            </button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const completed = milestones.filter((m) => m.status === 'completed').length;
  const inProgress = milestones.filter((m) => m.status === 'in_progress').length;
  const blocked = milestones.filter((m) => m.status === 'blocked').length;
  const progress = (completed / milestones.length) * 100;
  const todayStr = new Date().toISOString().slice(0, 10);
  const overdueCount = milestones.filter(
    (m) => m.status !== 'completed' && Boolean(m.dueDate && m.dueDate < todayStr),
  ).length;

  const handleCopyProgressMarkdown = async () => {
    const lines = [
      `# 项目里程碑进度报告 (${Math.round(progress)}%)`,
      `- **总体进度**：${completed} / ${milestones.length} 已完成（进行中 ${inProgress} · 阻塞 ${blocked}${overdueCount > 0 ? ` · 逾期 ${overdueCount}` : ''}）`,
      '',
      '## 里程碑列表',
      ...milestones.map((m) => {
        const st = m.stage ? ` [${stageLabelMap.get(m.stage) ?? m.stage}]` : '';
        const due = m.dueDate ? ` (截止: ${m.dueDate})` : '';
        return `- [${m.status === 'completed' ? 'x' : ' '}] **${m.title}**${st} — \`${m.status}\`${due}`;
      }),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedProgress(true);
      setTimeout(() => setCopiedProgress(false), 1800);
    } catch {
      // ignore in test/offline mode
    }
  };

  return (
    <Card data-testid="milestone-progress-widget">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Target className="h-4 w-4" />
            里程碑进度
          </CardTitle>
          <div className="flex items-center gap-1">
            {inProgress > 0 && (
              <button
                type="button"
                data-testid="milestone-summary-complete-active-btn"
                onClick={async () => {
                  if (typeof projectApi?.updateMilestone !== 'function') return;
                  try {
                    for (const m of milestones.filter((item) => item.status === 'in_progress')) {
                      await projectApi.updateMilestone(projectId, m.id, { status: 'completed' });
                    }
                    await fetchMilestones();
                  } catch {
                    // ignore in test/offline mode
                  }
                }}
                className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 text-ui-2xs font-medium text-primary hover:bg-primary/10"
              >
                完成进行中 ({inProgress})
              </button>
            )}
            <button
              type="button"
              data-testid="milestone-summary-save-l3-btn"
              onClick={async () => {
                if (savedProgressL3) return;
                setSavedProgressL3(true);
                if (typeof projectApi?.confirmKnowledge === 'function') {
                  try {
                    await projectApi.confirmKnowledge(projectId, {
                      entries: [
                        {
                          category: 'goal',
                          content: `项目里程碑进度快照：总体完成率 ${Math.round(progress)}%（已完成 ${completed}/${milestones.length}，进行中 ${inProgress}，阻塞 ${blocked}${overdueCount > 0 ? `，逾期 ${overdueCount}` : ''}）`,
                          importance: 7,
                          sourceMessageIds: [],
                          reasoning: '里程碑进度摘要沉淀至 L3 画像',
                        },
                      ],
                    });
                  } catch {
                    // ignore in test/offline mode
                  }
                }
              }}
              className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              {savedProgressL3 ? '已存进度 L3' : '沉淀进度至 L3'}
            </button>
            <button
              type="button"
              data-testid="milestone-summary-save-l4-btn"
              onClick={async () => {
                if (savedProgressL4) return;
                setSavedProgressL4(true);
                if (typeof projectApi?.addMaterial === 'function') {
                  try {
                    await projectApi.addMaterial(projectId, {
                      content: `# 项目里程碑进度快照 (${Math.round(progress)}%)\n${milestones.map((m) => `- [${m.status}] ${m.title}`).join('\n')}`,
                    });
                  } catch {
                    // ignore in test/offline mode
                  }
                }
              }}
              className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              {savedProgressL4 ? '已存 L4' : '存 L4'}
            </button>
            <button
              type="button"
              onClick={() => void handleCopyProgressMarkdown()}
              data-testid="milestone-summary-copy-md-btn"
              className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
              title="复制里程碑进度报告 Markdown"
            >
              {copiedProgress ? (
                <>
                  <Check className="h-3 w-3 text-emerald-500" />
                  已复制
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3" />
                  复制进度
                </>
              )}
            </button>
            <button
              type="button"
              onClick={() => void fetchMilestones()}
              data-testid="milestone-summary-refresh-btn"
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              title="刷新里程碑"
              aria-label="刷新里程碑"
            >
              <RefreshCw className="h-3 w-3" />
            </button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground">总体进度</span>
              {overdueCount > 0 && (
                <span
                  className="rounded bg-amber-500/15 px-1.5 py-0.5 text-ui-2xs font-medium text-amber-600"
                  data-testid="milestone-summary-overdue-badge"
                >
                  逾期 {overdueCount} 项
                </span>
              )}
            </div>
            <span className="font-medium">{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} className="h-2" />
        </div>

        {milestones.some((m) => m.stage) && (
          <div className="flex flex-wrap items-center gap-1 pt-1" data-testid="milestone-summary-stage-bar">
            {Array.from(
              milestones.reduce((acc, m) => {
                const st = m.stage || 'default';
                acc.set(st, (acc.get(st) ?? 0) + 1);
                return acc;
              }, new Map<string, number>()),
            ).map(([stageId, count]) => (
              <button
                key={stageId}
                type="button"
                data-testid={`milestone-summary-stage-pill-${stageId}`}
                onClick={() => setSelectedStageFilter((prev) => (prev === stageId ? null : stageId))}
                className={`rounded border px-1.5 py-0.5 text-ui-2xs transition-colors ${
                  selectedStageFilter === stageId
                    ? 'border-primary bg-primary/10 text-primary font-medium'
                    : 'border-border/70 bg-muted/30 text-muted-foreground hover:bg-muted'
                }`}
              >
                {stageLabelMap.get(stageId) ?? stageId}: {count}
              </button>
            ))}
          </div>
        )}

        <div className="grid grid-cols-3 gap-2 pt-2 border-t">
          <div className="flex items-center gap-1.5 text-xs">
            <CheckCircle2 className="h-3 w-3 text-green-500" />
            <span className="text-muted-foreground">完成：</span>
            <span className="font-medium">{completed}</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs">
            <Clock className="h-3 w-3 text-blue-500" />
            <span className="text-muted-foreground">进行：</span>
            <span className="font-medium">{inProgress}</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs">
            <AlertCircle className="h-3 w-3 text-orange-500" />
            <span className="text-muted-foreground">阻塞：</span>
            <span className="font-medium">{blocked}</span>
          </div>
        </div>

        {milestones.length > 0 && (
          <div className="pt-2 border-t">
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <div className="text-xs text-muted-foreground">最近里程碑</div>
              <div className="flex items-center gap-1" data-testid="milestone-summary-filter-bar">
                {(
                  [
                    { id: 'all', label: '全部' },
                    { id: 'active', label: '待办/进行' },
                    { id: 'completed', label: '已完成' },
                  ] as const
                ).map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    data-testid={`milestone-summary-filter-${tab.id}`}
                    onClick={() => setRecentFilter(tab.id)}
                    className={`rounded px-1.5 py-0.5 text-ui-2xs transition-colors ${
                      recentFilter === tab.id
                        ? 'bg-primary text-primary-foreground font-medium'
                        : 'bg-muted/50 text-muted-foreground hover:bg-muted'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-1">
              {milestones
                .filter((m) =>
                  (!selectedStageFilter || (m.stage || 'default') === selectedStageFilter) &&
                  (recentFilter === 'all'
                    ? true
                    : recentFilter === 'completed'
                      ? m.status === 'completed'
                      : m.status !== 'completed'),
                )
                .slice(0, 3)
                .map((milestone) => (
                <div key={milestone.id} className="flex items-center justify-between gap-2 text-xs">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      {getStatusIcon(milestone.status)}
                      <span className="font-medium truncate">{milestone.title}</span>
                      {milestone.stage && (
                        <span
                          className="shrink-0 rounded bg-muted px-1 py-0.5 text-ui-2xs text-muted-foreground"
                          data-testid={`milestone-summary-stage-${milestone.id}`}
                        >
                          {stageLabelMap.get(milestone.stage) ?? milestone.stage}
                        </span>
                      )}
                    </div>
                    {milestone.dueDate && (
                      <div className="text-muted-foreground ml-5">截止：{milestone.dueDate}</div>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                  <button
                    type="button"
                    data-testid={`milestone-summary-to-constraint-${milestone.id}`}
                    onClick={async () => {
                      if (promotedConstraintIds.has(milestone.id)) return;
                      setPromotedConstraintIds((prev) => new Set(prev).add(milestone.id));
                      if (typeof projectApi?.createConstraint === 'function') {
                        try {
                          await projectApi.createConstraint(projectId, {
                            category: 'deliverable_guard',
                            content: `里程碑交付准入标准 [${milestone.title}]`,
                            priority: 8,
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-primary hover:bg-primary/10"
                  >
                    {promotedConstraintIds.has(milestone.id) ? '已转L2' : '+L2'}
                  </button>
                  <button
                    type="button"
                    data-testid={`milestone-summary-to-l3-${milestone.id}`}
                    onClick={async () => {
                      if (promotedL3Ids.has(milestone.id)) return;
                      setPromotedL3Ids((prev) => new Set(prev).add(milestone.id));
                      if (typeof projectApi?.confirmKnowledge === 'function') {
                        try {
                          await projectApi.confirmKnowledge(projectId, {
                            entries: [
                              {
                                category: 'decision',
                                content: `里程碑进展 [${milestone.title}] (${milestone.status})`,
                                importance: 7,
                                sourceMessageIds: [],
                                reasoning: '里程碑进度摘要单条沉淀至 L3 画像',
                              },
                            ],
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    {promotedL3Ids.has(milestone.id) ? '已存L3' : '+L3'}
                  </button>
                  <button
                    type="button"
                    data-testid={`milestone-summary-to-l4-${milestone.id}`}
                    onClick={async () => {
                      if (promotedL4Ids.has(milestone.id)) return;
                      setPromotedL4Ids((prev) => new Set(prev).add(milestone.id));
                      if (typeof projectApi?.addMaterial === 'function') {
                        try {
                          await projectApi.addMaterial(projectId, {
                            content: `# 里程碑摘要归档：${milestone.title}\n- 状态：${milestone.status}\n- 阶段：${milestone.stage || '默认阶段'}`,
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    {promotedL4Ids.has(milestone.id) ? '已存L4' : '+L4'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleQuickToggleStatus(milestone)}
                    data-testid={`milestone-quick-toggle-${milestone.id}`}
                    className="shrink-0 rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    {milestone.status === 'completed' ? '重开' : '标记完成'}
                  </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function getStatusIcon(status: string) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="h-3 w-3 text-green-500" />;
    case 'in_progress':
      return <Clock className="h-3 w-3 text-blue-500" />;
    case 'blocked':
      return <AlertCircle className="h-3 w-3 text-orange-500" />;
    default:
      return <Clock className="h-3 w-3 text-gray-400" />;
  }
}
