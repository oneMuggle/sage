/**
 * GitStatusSection — 侧边栏 Git 状态面板（VSCode 风格）。
 *
 * 显示当前分支 + 变更文件列表，支持按状态过滤，点击文件打开 diff 视图。
 * 数据来源: projectApi.list() 第一个（最近打开的）项目的 path。
 * 自动刷新: 30 秒轮询（组件可见时）。
 * 非 git 目录静默降级（不显示 section 内容）。
 */

import { GitBranch, MoreVertical, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  getGitStatus,
  type GitFileChange,
  type GitStatusResponse,
} from '../../../shared/api/gitStatusApi';
import { projectApi, type ProjectSummary } from '../../../shared/api/projectApi';
import { type TranslationKey, useI18n } from '../../../shared/lib/i18n';
import { SiderSection } from '../SiderSection';
import { GitDiffDrawer } from './GitDiffDrawer';

interface GitStatusSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

type GitFilterCategory = 'all' | 'staged' | 'modified' | 'untracked';

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

interface FilterItem {
  id: GitFilterCategory;
  labelKey: TranslationKey;
}

const FILTER_ITEMS: FilterItem[] = [
  { id: 'all', labelKey: 'git.filter_all' },
  { id: 'staged', labelKey: 'git.filter_staged' },
  { id: 'modified', labelKey: 'git.filter_modified' },
  { id: 'untracked', labelKey: 'git.filter_untracked' },
];

export function GitStatusSection({ collapsed, onToggleCollapsed }: GitStatusSectionProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<GitStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [projectPath, setProjectPath] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState<GitFilterCategory>('all');
  const [copiedBranch, setCopiedBranch] = useState(false);
  const [copiedFilePath, setCopiedFilePath] = useState<string | null>(null);
  const [copiedAllPaths, setCopiedAllPaths] = useState(false);
  const [copiedMarkdown, setCopiedMarkdown] = useState(false);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [diffTarget, setDiffTarget] = useState<{ path: string; status: string } | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 获取第一个项目的路径
  const resolveProjectPath = useCallback(async () => {
    try {
      const projects: ProjectSummary[] = await projectApi.list();
      if (projects.length > 0) {
        const sorted = [...projects].sort((a, b) => (b.lastOpenedAt ?? 0) - (a.lastOpenedAt ?? 0));
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

  // 复制分支名
  const handleCopyBranch = useCallback(async (e: React.MouseEvent, branch: string) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await navigator.clipboard?.writeText(branch || 'HEAD');
      setCopiedBranch(true);
      setTimeout(() => setCopiedBranch(false), 1500);
    } catch {
      // ignore
    }
  }, []);

  // 复制单文件路径
  const handleCopyPath = useCallback(async (e: React.MouseEvent, filePath: string) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await navigator.clipboard?.writeText(filePath);
      setCopiedFilePath(filePath);
      setTimeout(() => setCopiedFilePath(null), 1500);
    } catch {
      // ignore
    }
  }, []);

  // 复制全部路径
  const handleCopyAllPaths = useCallback(async (files: GitFileChange[]) => {
    try {
      await navigator.clipboard?.writeText(files.map((f) => f.path).join('\n'));
      setCopiedAllPaths(true);
      setTimeout(() => setCopiedAllPaths(false), 1500);
    } catch {
      // ignore
    }
    setMoreMenuOpen(false);
  }, []);

  // 复制 Markdown 清单
  const handleCopyMarkdown = useCallback(async (files: GitFileChange[], branch: string | null) => {
    const md = `# Git Changes (${branch || 'HEAD'})\n${files.map((f) => `- [${statusBadge(f.status)}] \`${f.path}\``).join('\n')}`;
    try {
      await navigator.clipboard?.writeText(md);
      setCopiedMarkdown(true);
      setTimeout(() => setCopiedMarkdown(false), 1500);
    } catch {
      // ignore
    }
    setMoreMenuOpen(false);
  }, []);

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
          <p className="text-ui-xs text-text-muted px-2 py-1 italic">{t('git.not_a_repo')}</p>
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
          <p className="text-ui-xs text-text-muted px-2 py-1 italic">{t('git.no_project')}</p>
        )}
      />
    );
  }

  const fileCount = status?.files.length ?? 0;

  return (
    <>
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
              <button
                type="button"
                onClick={(e) => handleCopyBranch(e, status.branch ?? '')}
                className="text-ui-xs text-text-muted max-w-[68px] truncate hover:text-text"
                title={t('git.copy_branch')}
              >
                {copiedBranch ? t('git.copied') : status.branch}
              </button>
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
              <p className="text-ui-xs text-text-muted px-2 py-1 italic">{t('git.loading')}</p>
            );
          }

          if (!status || status.files.length === 0) {
            return <p className="text-ui-xs text-text-muted px-2 py-1 italic">{t('git.clean')}</p>;
          }

          const filteredFiles = status.files.filter((f) => {
            if (filterCategory === 'all') return true;
            if (filterCategory === 'staged') return f.status === 'staged';
            if (filterCategory === 'untracked') return f.status === 'untracked';
            return (
              f.status === 'modified' ||
              f.status === 'deleted' ||
              f.status === 'renamed' ||
              f.status === 'conflicted'
            );
          });

          return (
            <div className="space-y-1">
              {/* Filter bar */}
              <div className="flex items-center gap-1 px-2 pt-0.5">
                {FILTER_ITEMS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    data-testid={`git-filter-${item.id}`}
                    onClick={() => setFilterCategory(item.id)}
                    className={`rounded px-1.5 py-0.5 text-ui-2xs transition-colors ${
                      filterCategory === item.id
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-bg-secondary text-text-muted hover:text-text'
                    }`}
                  >
                    {t(item.labelKey)}
                  </button>
                ))}
                {/* "..." more menu */}
                <div className="relative ml-auto">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setMoreMenuOpen((prev) => !prev);
                    }}
                    className="w-5 h-5 flex items-center justify-center rounded text-text-muted hover:text-text hover:bg-bg-hover"
                    title={t('git.more_actions')}
                    aria-label={t('git.more_actions')}
                  >
                    <MoreVertical className="w-3 h-3" />
                  </button>
                  {moreMenuOpen && (
                    <div className="absolute right-0 top-full mt-1 z-10 min-w-[120px] rounded-md border border-border bg-surface-elevated dark:bg-surface shadow-lg py-1">
                      <button
                        type="button"
                        onClick={() => handleCopyAllPaths(filteredFiles)}
                        className="w-full text-left px-3 py-1.5 text-ui-xs text-text hover:bg-bg-hover"
                      >
                        {copiedAllPaths ? t('git.copied') : t('git.copy_all_paths')}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleCopyMarkdown(filteredFiles, status.branch)}
                        className="w-full text-left px-3 py-1.5 text-ui-xs text-text hover:bg-bg-hover"
                      >
                        {copiedMarkdown ? t('git.copied') : t('git.copy_markdown')}
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* File list */}
              <ul className="flex flex-col" data-testid="git-status-list">
                {filteredFiles.map((file) => (
                  <li
                    key={`${file.status}-${file.path}`}
                    className="group flex items-center gap-1.5 px-2 py-1 rounded-radius-sm hover:bg-bg-hover cursor-pointer"
                    title={file.path}
                    onClick={() => setDiffTarget({ path: file.path, status: file.status })}
                  >
                    <span
                      className={`text-ui-xs font-mono w-3 text-center flex-shrink-0 ${statusColor(file.status)}`}
                    >
                      {statusBadge(file.status)}
                    </span>
                    <span className="text-ui-xs text-text truncate flex-1">{file.path}</span>
                    <button
                      type="button"
                      onClick={(e) => handleCopyPath(e, file.path)}
                      className="shrink-0 opacity-0 group-hover:opacity-100 rounded px-1 py-0.5 text-ui-2xs text-text-muted hover:text-text transition-opacity"
                      title={t('git.copy_path')}
                    >
                      {copiedFilePath === file.path ? t('git.copied') : t('git.copy_path')}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          );
        }}
      />

      {/* Diff drawer */}
      {projectPath && diffTarget && (
        <GitDiffDrawer
          isOpen={Boolean(diffTarget)}
          onClose={() => setDiffTarget(null)}
          projectPath={projectPath}
          filePath={diffTarget.path}
          fileStatus={diffTarget.status}
        />
      )}
    </>
  );
}
