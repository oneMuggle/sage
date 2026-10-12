/**
 * 里程碑进度 Widget (2026-09-25; Phase P15 空状态一键播种与概览快捷完成切换 2026-10-12)
 *
 * 项目类型分类系统 - Phase 4.3
 * 显示项目里程碑的进度统计、空状态一键生成形态推荐里程碑与快捷状态切换
 */

import { Target, CheckCircle2, Clock, AlertCircle, Sparkles } from 'lucide-react';
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

  const fetchMilestones = useCallback(async () => {
    try {
      setLoading(true);
      const list = await projectApi.listMilestones(projectId);
      setMilestones(list);
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

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Target className="h-4 w-4" />
          里程碑进度
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">总体进度</span>
            <span className="font-medium">{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} className="h-2" />
        </div>

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
            <div className="text-xs text-muted-foreground mb-1">最近里程碑</div>
            <div className="space-y-1">
              {milestones.slice(0, 3).map((milestone) => (
                <div key={milestone.id} className="flex items-center justify-between gap-2 text-xs">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      {getStatusIcon(milestone.status)}
                      <span className="font-medium truncate">{milestone.title}</span>
                    </div>
                    {milestone.dueDate && (
                      <div className="text-muted-foreground ml-5">截止：{milestone.dueDate}</div>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleQuickToggleStatus(milestone)}
                    data-testid={`milestone-quick-toggle-${milestone.id}`}
                    className="shrink-0 rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    {milestone.status === 'completed' ? '重开' : '标记完成'}
                  </button>
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
