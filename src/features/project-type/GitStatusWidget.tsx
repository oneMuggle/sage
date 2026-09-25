/**
 * Git 状态 Widget (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.3
 * Coding 项目专属：显示 Git 仓库状态
 */

import { GitBranch, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useState, useEffect } from 'react';

import { invoke } from '../../shared/api/desktopInvoke';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';

export interface GitStatusWidgetProps {
  projectId: string;
}

interface GitStatus {
  is_repo: boolean;
  current_branch?: string;
  modified_files: string[];
  staged_files: string[];
  untracked_files: string[];
  recent_commits: Array<{
    sha: string;
    author: string;
    date: string;
    message: string;
  }>;
}

export function GitStatusWidget({ projectId }: GitStatusWidgetProps) {
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchStatus() {
      try {
        setLoading(true);
        const result = await invoke<GitStatus>('projects_git_status', { projectId });
        setStatus(result);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : '获取 Git 状态失败');
      } finally {
        setLoading(false);
      }
    }

    fetchStatus();
  }, [projectId]);

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <GitBranch className="h-4 w-4" />
            Git 状态
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">加载中...</div>
        </CardContent>
      </Card>
    );
  }

  if (error || !status || !status.is_repo) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <GitBranch className="h-4 w-4" />
            Git 状态
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <AlertCircle className="h-4 w-4" />
            {error || '非 Git 仓库'}
          </div>
        </CardContent>
      </Card>
    );
  }

  const totalChanges =
    status.modified_files.length + status.staged_files.length + status.untracked_files.length;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <GitBranch className="h-4 w-4" />
          Git 状态
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {/* 分支信息 */}
        <div className="text-sm">
          <span className="text-muted-foreground">分支：</span>
          <span className="font-medium">{status.current_branch}</span>
        </div>

        {/* 变更统计 */}
        {totalChanges > 0 ? (
          <div className="space-y-1">
            {status.staged_files.length > 0 && (
              <div className="flex items-center gap-2 text-xs">
                <CheckCircle2 className="h-3 w-3 text-green-500" />
                <span className="text-muted-foreground">已暂存：</span>
                <span>{status.staged_files.length} 个文件</span>
              </div>
            )}
            {status.modified_files.length > 0 && (
              <div className="flex items-center gap-2 text-xs">
                <AlertCircle className="h-3 w-3 text-orange-500" />
                <span className="text-muted-foreground">已修改：</span>
                <span>{status.modified_files.length} 个文件</span>
              </div>
            )}
            {status.untracked_files.length > 0 && (
              <div className="flex items-center gap-2 text-xs">
                <AlertCircle className="h-3 w-3 text-gray-500" />
                <span className="text-muted-foreground">未跟踪：</span>
                <span>{status.untracked_files.length} 个文件</span>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-green-600 dark:text-green-400">
            <CheckCircle2 className="h-4 w-4" />
            工作区干净
          </div>
        )}

        {/* 最近提交 */}
        {status.recent_commits.length > 0 && (
          <div className="pt-2 border-t">
            <div className="text-xs text-muted-foreground mb-1">最近提交</div>
            <div className="space-y-1">
              {status.recent_commits.slice(0, 3).map((commit) => (
                <div key={commit.sha} className="text-xs">
                  <div className="font-medium truncate">{commit.message}</div>
                  <div className="text-muted-foreground">
                    {commit.author} · {commit.date.split(' ')[0]}
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
