/**
 * 里程碑进度 Widget (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.3
 * 显示项目里程碑的进度统计
 */

import { useState, useEffect } from 'react';
import { Target, CheckCircle2, Clock, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';
import { Progress } from '../../shared/ui/Progress';
import { projectApi, type ProjectMilestone } from '../../shared/api';

export interface MilestoneProgressWidgetProps {
  projectId: string;
}

export function MilestoneProgressWidget({ projectId }: MilestoneProgressWidgetProps) {
  const [milestones, setMilestones] = useState<ProjectMilestone[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchMilestones() {
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
    }

    fetchMilestones();
  }, [projectId]);

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
          <div className="text-xs text-muted-foreground">
            暂无里程碑。设置里程碑以跟踪项目进度。
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
        {/* 进度条 */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">总体进度</span>
            <span className="font-medium">{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} className="h-2" />
        </div>

        {/* 状态统计 */}
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

        {/* 最近里程碑 */}
        {milestones.length > 0 && (
          <div className="pt-2 border-t">
            <div className="text-xs text-muted-foreground mb-1">最近里程碑</div>
            <div className="space-y-1">
              {milestones.slice(0, 3).map((milestone) => (
                <div key={milestone.id} className="text-xs">
                  <div className="flex items-center gap-1.5">
                    {getStatusIcon(milestone.status)}
                    <span className="font-medium truncate">{milestone.title}</span>
                  </div>
                  {milestone.dueDate && (
                    <div className="text-muted-foreground ml-5">截止：{milestone.dueDate}</div>
                  )}
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
