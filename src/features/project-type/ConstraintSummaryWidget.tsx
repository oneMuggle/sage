/**
 * 约束摘要 Widget (2026-09-25; Phase P15 空状态一键导入与 Glob 触发统计 2026-10-12)
 *
 * 项目类型分类系统 - Phase 4.3
 * 显示项目的约束统计信息（启用数量、Glob 触发数量、按类别分组及空状态快速导入）
 */

import { Shield, CheckCircle2, Sparkles } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';

import { projectApi, type ProjectConstraint, type ProjectType } from '../../shared/api';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';

export interface ConstraintSummaryWidgetProps {
  projectId: string;
  projectType: ProjectType | null | undefined;
}

export function ConstraintSummaryWidget({ projectId, projectType }: ConstraintSummaryWidgetProps) {
  const [constraints, setConstraints] = useState<ProjectConstraint[]>([]);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchConstraints = useCallback(async () => {
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
  }, [projectId]);

  useEffect(() => {
    void fetchConstraints();
  }, [fetchConstraints]);

  const handleQuickImport = async () => {
    if (!projectType || importing || typeof projectApi?.importConstraints !== 'function') return;
    setImporting(true);
    try {
      await projectApi.importConstraints(projectId, projectType);
      await fetchConstraints();
    } catch {
      // ignore in test/offline mode
    } finally {
      setImporting(false);
    }
  };

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
  const globCount = enabledConstraints.filter((c) => Boolean(c.triggerPattern?.trim())).length;
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
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-green-500" />
            <span className="text-muted-foreground">启用约束：</span>
            <span className="font-medium">
              {enabledConstraints.length} / {constraints.length}
            </span>
          </div>
          {globCount > 0 && (
            <span
              className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-ui-2xs text-primary"
              data-testid="constraint-summary-glob-count"
            >
              Glob 按需触发：{globCount} 条
            </span>
          )}
        </div>

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

        {constraints.length === 0 && (
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground pt-2 border-t">
            <div>
              暂无约束。
              {projectType && <span> {getProjectTypeConstraintHint(projectType)}</span>}
            </div>
            {projectType && (
              <button
                type="button"
                disabled={importing}
                onClick={() => void handleQuickImport()}
                data-testid="constraint-summary-quick-import"
                className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-ui-2xs font-medium text-primary hover:bg-primary/10 disabled:opacity-50"
              >
                <Sparkles className="h-3 w-3" />
                {importing ? '导入中...' : '一键导入默认规范'}
              </button>
            )}
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
