/**
 * GitStatusSection — ZCode-inspired 侧边栏 Git 状态面板。
 *
 * 显示当前工作区的分支 + 变更文件列表。
 * 数据来源: projectApi.list() 第一个（最近打开的）项目的 path。
 * 自动刷新: 30 秒轮询（组件可见时）。
 * 非 git 目录静默降级（不显示 section 内容）。
 */

import { GitBranch, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { getGitStatus, type GitFileChange, type GitStatusResponse } from '../../../shared/api/gitStatusApi';
import { projectApi, type ProjectSummary } from '../../../shared/api/projectApi';
import { useI18n } from '../../../shared/lib/i18n';
import { SiderSection } from '../SiderSection';

interface GitStatusSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

const REFRESH_INTERVAL = 30_000; // 30 seconds

/** 状态徽标颜色 */
function statusColor(status: GitFileChange['status']): string {
  switch (status) {
    case 'conflicted':
      return 'text-error';
    case 'staged':
      return 'text-success';
    case 'modified':
      return 'text-warning';
    case 'untracked':
      return 'text-info';
    case 'deleted':
      return 'text-error';
    case 'renamed':
      return 'text-info';
    default:
      return 'text-text-muted';
  }
}

/** 状态单字母标记 */
function statusBadge(status: GitFileChange['status']): string {
  switch (status) {
    case 'conflicted':
      return '!';
    case 'staged':
      return 'S';
    case 'modified':
      return 'M';
    case 'untracked':
      return '?';
    case 'deleted':
      return 'D';
    case 'renamed':
      return 'R';
    default:
      return '?';
  }
}

export function GitStatusSection({ collapsed, onToggleCollapsed }: GitStatusSectionProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<GitStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [projectPath, setProjectPath] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 获取第一个项目的路径
  const resolveProjectPath = useCallback(async () => {
    try {
      const projects: ProjectSummary[] = await projectApi.list();
      if (projects.length > 0) {
        // 按最近打开排序，取第一个
        const sorted = [...projects].sort(
          (a, b) => (b.lastOpenedAt ?? 0) - (a.lastOpenedAt ?? 0),
        );
        setProjectPath(sorted[0].path);
        return sorted[0].path;
      }
    } catch {
      // 静默降级
    }
    setProjectPath(null);
    return null;
  }, []);

  // 拉取 git status
  const fetchStatus = useCallback(async () => {
    let path = projectPath;
    if (!path) {
      path = await resolveProjectPath();
    }
    if (!path) return;

    setLoading(true);
    try {
      const result = await getGitStatus(path);
      setStatus(result);
    } catch {
      // 后端不可用 — 静默降级
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, [projectPath, resolveProjectPath]);

  // 初始加载 + 定时刷新
  useEffect(() => {
    void fetchStatus();

    timerRef.current = setInterval(() => {
      void fetchStatus();
    }, REFRESH_INTERVAL);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [fetchStatus]);

  // 手动刷新
  const handleRefresh = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      void fetchStatus();
    },
    [fetchStatus],
  );

  // 非 git 仓库或无项目 → 不渲染内容
  if (!loading && status && !status.is_git_repo) {
    return (
      <SiderSection
        sectionKey="git"
        label={t('git.title')}
        icon={GitBranch}
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
        render={() => (
          <p className="text-ui-xs text-text-muted px-2 py-1 italic">
            {t('git.not_a_repo')}
          </p>
        )}
      />
    );
  }

  if (!loading && !status && !projectPath) {
    return (
      <SiderSection
        sectionKey="git"
        label={t('git.title')}
        icon={GitBranch}
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
        render={() => (
          <p className="text-ui-xs text-text-muted px-2 py-1 italic">
            {t('git.no_project')}
          </p>
        )}
      />
    );
  }

  const fileCount = status?.files.length ?? 0;

  return (
    <SiderSection
      sectionKey="git"
      label={t('git.title')}
      icon={GitBranch}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      trailing={
        <div className="flex items-center gap-1">
          {fileCount > 0 && (
            <span className="text-ui-xs bg-warning/10 text-warning px-1 rounded-full">
              {fileCount}
            </span>
          )}
          {status?.branch && (
            <span className="text-ui-xs text-text-muted max-w-[60px] truncate">
              {status.branch}
            </span>
          )}
          <button
            onClick={handleRefresh}
            title={t('git.refresh')}
            aria-label={t('git.refresh')}
            className="w-5 h-5 flex items-center justify-center rounded text-text-muted hover:text-text hover:bg-bg-hover"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      }
      render={() => {
        if (loading && !status) {
          return (
            <p className="text-ui-xs text-text-muted px-2 py-1 italic">
              {t('git.loading')}
            </p>
          );
        }

        if (!status || status.files.length === 0) {
          return (
            <p className="text-ui-xs text-text-muted px-2 py-1 italic">
              {t('git.clean')}
            </p>
          );
        }

        return (
          <ul className="flex flex-col" data-testid="git-status-list">
            {status.files.slice(0, 12).map((file) => (
              <li
                key={`${file.status}-${file.path}`}
                className="group flex items-center gap-1.5 px-2 py-1 rounded-radius-sm hover:bg-bg-hover"
                title={file.path}
              >
                <span
                  className={`text-ui-xs font-mono w-3 text-center flex-shrink-0 ${statusColor(file.status)}`}
                >
                  {statusBadge(file.status)}
                </span>
                <span className="text-ui-xs text-text truncate flex-1">
                  {file.path}
                </span>
              </li>
            ))}
            {status.files.length > 12 && (
              <li className="text-ui-xs text-text-muted px-2 py-0.5 italic">
                +{status.files.length - 12} more
              </li>
            )}
          </ul>
        );
      }}
    />
  );
}
