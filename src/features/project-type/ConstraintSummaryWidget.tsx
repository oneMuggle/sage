/**
 * 约束摘要 Widget (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.3
 * 显示项目的约束统计信息（启用数量、按类别分组）
 */

import { useState, useEffect } from 'react';
import { Shield, CheckCircle2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';
import { projectApi, type ProjectConstraint, type ProjectType } from '../../shared/api';

export interface ConstraintSummaryWidgetProps {
  projectId: string;
  projectType: ProjectType | null | undefined;
}

export function ConstraintSummaryWidget({ projectId, projectType }: ConstraintSummaryWidgetProps) {
  const [constraints, setConstraints] = useState<ProjectConstraint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchConstraints() {
      try {
        setLoading(true);
        const list = await projectApi.listConstraints(projectId);
        setConstraints(list);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : '获取约束失败');
      } finally {
        setLoading(false);
      }
    }

    fetchConstraints();
  }, [projectId]);

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Shield className="h-4 w-4" />
            约束统计
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
            <Shield className="h-4 w-4" />
            约束统计
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-red-500">{error}</div>
        </CardContent>
      </Card>
    );
  }

  const enabledConstraints = constraints.filter((c) => c.enabled);
  const categoryCount = new Map<string, number>();
  enabledConstraints.forEach((c) => {
    categoryCount.set(c.category, (categoryCount.get(c.category) || 0) + 1);
  });

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Shield className="h-4 w-4" />
          约束统计
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {/* 总启用约束 */}
        <div className="flex items-center gap-2 text-sm">
          <CheckCircle2 className="h-4 w-4 text-green-500" />
          <span className="text-muted-foreground">启用约束：</span>
          <span className="font-medium">
            {enabledConstraints.length} / {constraints.length}
          </span>
        </div>

        {/* 按类别统计 */}
        {categoryCount.size > 0 && (
          <div className="pt-2 border-t">
            <div className="text-xs text-muted-foreground mb-1">按类别</div>
            <div className="space-y-1">
              {Array.from(categoryCount.entries())
                .sort((a, b) => b[1] - a[1])
                .slice(0, 5)
                .map(([category, count]) => (
                  <div key={category} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{category}</span>
                    <span className="font-medium">{count}</span>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* 无约束提示 */}
        {constraints.length === 0 && (
          <div className="text-xs text-muted-foreground pt-2 border-t">
            暂无约束。
            {projectType && <span> {getProjectTypeConstraintHint(projectType)}</span>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function getProjectTypeConstraintHint(projectType: ProjectType): string {
  const hints: Record<ProjectType, string> = {
    coding: '可导入代码风格、Git 提交规范模板',
    research: '可导入学术写作、文献引用规范模板',
    business: '可导入商务文档、格式规范模板',
    personal: '可导入笔记组织、学习规划模板',
  };
  return hints[projectType];
}
