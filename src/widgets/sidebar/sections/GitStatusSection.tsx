/**
 * GitStatusSection — ZCode-inspired 侧边栏 Git 状态面板 (Phase P31 变更状态筛选与 Markdown 复制)。
 *
 * 显示当前工作区的分支 + 变更文件列表，支持按状态（全部/暂存/修改/未跟踪）过滤及一键复制变更清单。
 * 数据来源: projectApi.list() 第一个（最近打开的）项目的 path。
 * 自动刷新: 30 秒轮询（组件可见时）。
 * 非 git 目录静默降级（不显示 section 内容）。
 */

import { Check, Copy, GitBranch, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { getGitStatus, type GitFileChange, type GitStatusResponse } from '../../../shared/api/gitStatusApi';
import { projectApi, type ProjectSummary } from '../../../shared/api/projectApi';
import { useI18n } from '../../../shared/lib/i18n';
import { SiderSection } from '../SiderSection';

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

export function GitStatusSection({ collapsed, onToggleCollapsed }: GitStatusSectionProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<GitStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [projectPath, setProjectPath] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState<GitFilterCategory>('all');
  const [copiedMd, setCopiedMd] = useState(false);
  const [savedSiderL4, setSavedSiderL4] = useState(false);
  const [savedSiderL3, setSavedSiderL3] = useState(false);
  const [convertedSiderMilestone, setConvertedSiderMilestone] = useState(false);
  const [ingestedPaths, setIngestedPaths] = useState<Set<string>>(new Set());
  const [guardedPaths, setGuardedPaths] = useState<Set<string>>(new Set());
  const [l3Paths, setL3Paths] = useState<Set<string>>(new Set());
  const [copiedFilePath, setCopiedFilePath] = useState<string | null>(null);
  const [copiedBranch, setCopiedBranch] = useState(false);
  const [guardedAllSider, setGuardedAllSider] = useState(false);
  const [ingestedAllSider, setIngestedAllSider] = useState(false);
  const [copiedSiderPaths, setCopiedSiderPaths] = useState(false);
  const [milestonePaths, setMilestonePaths] = useState<Set<string>>(new Set());
  const [savedAllSiderL3, setSavedAllSiderL3] = useState(false);
  const [createdAllSiderMilestones, setCreatedAllSiderMilestones] = useState(false);
  const [copiedSiderJson, setCopiedSiderJson] = useState(false);
  const [copiedFileJsonPath, setCopiedFileJsonPath] = useState<string | null>(null);
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
        setProjectId(sorted[0].id);
        return sorted[0].path;
      }
    } catch {
      // 静默降级
    }
    setProjectPath(null);
    setProjectId(null);
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

  const handleCopyChangesMarkdown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (!status || status.files.length === 0) return;
      const lines = [
        `# 侧边栏 Git 变更清单 (${status.branch || 'HEAD'})`,
        '',
        ...status.files.map((f) => `- [${statusBadge(f.status)}] \`${f.path}\``),
      ];
      try {
        void navigator.clipboard?.writeText(lines.join('\n'));
        setCopiedMd(true);
        setTimeout(() => setCopiedMd(false), 1800);
      } catch {
        // ignore in test/offline mode
      }
    },
    [status],
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
            <button
              type="button"
              data-testid="git-sider-copy-branch-btn"
              onClick={async (e) => {
                e.preventDefault();
                e.stopPropagation();
                try {
                  await navigator.clipboard?.writeText(status.branch || 'HEAD');
                  setCopiedBranch(true);
                  setTimeout(() => setCopiedBranch(false), 1500);
                } catch {
                  // ignore in test/offline mode
                }
              }}
              className="text-ui-xs text-text-muted max-w-[68px] truncate hover:text-text"
              title="复制当前分支名称"
            >
              {copiedBranch ? '已复制' : status.branch}
            </button>
          )}
          {fileCount > 0 && (
            <button
              type="button"
              onClick={handleCopyChangesMarkdown}
              data-testid="git-sider-copy-md-btn"
              title="复制 Git 变更清单 Markdown"
              className="w-5 h-5 flex items-center justify-center rounded text-text-muted hover:text-text hover:bg-bg-hover"
            >
              {copiedMd ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
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

        const filteredFiles = status.files.filter((f) => {
          if (filterCategory === 'all') return true;
          if (filterCategory === 'staged') return f.status === 'staged';
          if (filterCategory === 'untracked') return f.status === 'untracked';
          return f.status === 'modified' || f.status === 'deleted' || f.status === 'renamed' || f.status === 'conflicted';
        });

        return (
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-1 px-2 pt-0.5" data-testid="git-sider-filter-bar">
              {(
                [
                  { id: 'all', label: '全部' },
                  { id: 'staged', label: '暂存' },
                  { id: 'modified', label: '修改' },
                  { id: 'untracked', label: '未跟踪' },
                ] as const
              ).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setFilterCategory(item.id)}
                  data-testid={`git-sider-filter-${item.id}`}
                  className={`rounded px-1.5 py-0.5 text-ui-2xs transition-colors ${
                    filterCategory === item.id
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-bg-secondary text-text-muted hover:text-text'
                  }`}
                >
                  {item.label}
                </button>
              ))}
              {projectId && (
                <>
                  <button
                    type="button"
                    data-testid="git-sider-save-l4-btn"
                    onClick={async () => {
                      if (savedSiderL4) return;
                      setSavedSiderL4(true);
                      if (typeof projectApi?.addMaterial === 'function') {
                        try {
                          await projectApi.addMaterial(projectId, {
                            content: `# 侧边栏 Git 变更快照 (${status.branch || 'HEAD'})\n${status.files.map((f) => `- [${statusBadge(f.status)}] \`${f.path}\``).join('\n')}`,
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-bg-secondary px-1.5 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                  >
                    {savedSiderL4 ? '已存L4' : '存L4'}
                  </button>
                  <button
                    type="button"
                    data-testid="git-sider-save-l3-btn"
                    onClick={async () => {
                      if (savedSiderL3) return;
                      setSavedSiderL3(true);
                      if (typeof projectApi?.confirmKnowledge === 'function') {
                        try {
                          await projectApi.confirmKnowledge(projectId, {
                            entries: [
                              {
                                category: 'note',
                                content: `侧边栏 Git 变更快照 (${status.branch || 'HEAD'})：共 ${status.files.length} 个变更文件`,
                                importance: 6,
                                sourceMessageIds: [],
                                reasoning: '侧边栏 Git 变更状态沉淀至 L3 画像',
                              },
                            ],
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-bg-secondary px-1.5 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                  >
                    {savedSiderL3 ? '已存L3' : '存L3'}
                  </button>
                  <button
                    type="button"
                    data-testid="git-sider-to-milestone-btn"
                    onClick={async () => {
                      if (convertedSiderMilestone) return;
                      setConvertedSiderMilestone(true);
                      if (typeof projectApi?.createMilestone === 'function') {
                        try {
                          await projectApi.createMilestone(projectId, {
                            title: `[Git 变更审校] ${status.branch || 'HEAD'} (${filteredFiles.length} 个文件)`,
                            description: filteredFiles.map((f) => f.path).join('、'),
                            status: 'in_progress',
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-bg-secondary px-1.5 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                  >
                    {convertedSiderMilestone ? '已转里程碑' : '转里程碑'}
                  </button>
                  <button
                    type="button"
                    data-testid="git-sider-guard-all-btn"
                    onClick={async () => {
                      if (guardedAllSider) return;
                      setGuardedAllSider(true);
                      if (typeof projectApi?.createConstraint === 'function') {
                        for (const f of filteredFiles) {
                          try {
                            await projectApi.createConstraint(projectId, {
                              category: 'file_change_guard',
                              content: `侧边栏 Git 变更护栏：修改 ${f.path} 须通过契约与单测核验`,
                              triggerPattern: f.path,
                              priority: 8,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }
                    }}
                    className="rounded border border-border bg-bg-secondary px-1.5 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                  >
                    {guardedAllSider ? '已全护栏' : '全护栏L2'}
                  </button>
                  <button
                    type="button"
                    data-testid="git-sider-ingest-all-btn"
                    onClick={async () => {
                      if (ingestedAllSider) return;
                      setIngestedAllSider(true);
                      if (typeof projectApi?.addMaterialFromFile === 'function') {
                        for (const f of filteredFiles.slice(0, 12)) {
                          try {
                            await projectApi.addMaterialFromFile(projectId, f.path);
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }
                    }}
                    className="rounded border border-border bg-bg-secondary px-1.5 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                  >
                    {ingestedAllSider ? '已全入库' : '全入库L4'}
                  </button>
                  <button
                    type="button"
                    data-testid="git-sider-copy-paths-btn"
                    onClick={async () => {
                      try {
                        await navigator.clipboard?.writeText(filteredFiles.map((f) => f.path).join('\n'));
                        setCopiedSiderPaths(true);
                        setTimeout(() => setCopiedSiderPaths(false), 1500);
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="rounded border border-border bg-bg-secondary px-1.5 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                  >
                    {copiedSiderPaths ? '已复制路径' : '复制路径'}
                  </button>
                  <button
                    type="button"
                    data-testid="git-sider-copy-json-btn"
                    onClick={async () => {
                      setCopiedSiderJson(true);
                      setTimeout(() => {
                        if (typeof window !== 'undefined') setCopiedSiderJson(false);
                      }, 1500);
                      try {
                        await navigator.clipboard?.writeText(
                          JSON.stringify(
                            {
                              branch: status.branch || 'HEAD',
                              isGitRepo: status.is_git_repo,
                              filterCategory,
                              totalChanges: status.files.length,
                              filteredCount: filteredFiles.length,
                              files: filteredFiles.map((f) => ({ path: f.path, status: f.status })),
                            },
                            null,
                            2,
                          ),
                        );
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="rounded border border-border bg-bg-secondary px-1.5 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                  >
                    {copiedSiderJson ? '已复制JSON' : '复制JSON'}
                  </button>
                  <button
                    type="button"
                    data-testid="git-sider-all-to-l3-btn"
                    onClick={async () => {
                      if (savedAllSiderL3) return;
                      setSavedAllSiderL3(true);
                      if (typeof projectApi?.confirmKnowledge === 'function') {
                        try {
                          await projectApi.confirmKnowledge(projectId, {
                            entries: [
                              {
                                category: 'note',
                                content: `侧边栏批量沉淀 Git 变更 (${status.branch || 'HEAD'} · ${filteredFiles.length} 个文件)：${filteredFiles.slice(0, 12).map((f) => `${f.path}[${f.status}]`).join('、')}`,
                                importance: 6,
                                sourceMessageIds: [],
                                reasoning: '侧边栏 Git 筛选文件批量沉淀至 L3 画像',
                              },
                            ],
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-bg-secondary px-1.5 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                  >
                    {savedAllSiderL3 ? '已全存L3' : '全存L3'}
                  </button>
                  <button
                    type="button"
                    data-testid="git-sider-all-to-milestone-btn"
                    onClick={async () => {
                      if (createdAllSiderMilestones) return;
                      setCreatedAllSiderMilestones(true);
                      if (typeof projectApi?.createMilestone === 'function') {
                        try {
                          await projectApi.createMilestone(projectId, {
                            title: `[Git 批量变更复核] ${status.branch || 'HEAD'} (${filteredFiles.length} 个文件)`,
                            description: filteredFiles
                              .slice(0, 12)
                              .map((f) => `${f.path} [${f.status}]`)
                              .join(' · '),
                            status: 'pending',
                          });
                        } catch {
                          // ignore in test/offline mode
                        }
                      }
                    }}
                    className="rounded border border-border bg-bg-secondary px-1.5 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                  >
                    {createdAllSiderMilestones ? '已全建里程碑' : '全建里程碑'}
                  </button>
                </>
              )}
            </div>
            <ul className="flex flex-col" data-testid="git-status-list">
              {filteredFiles.slice(0, 12).map((file) => (
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
                  {projectId && (
                    <button
                      type="button"
                      data-testid={`git-sider-ingest-${file.path}`}
                      onClick={async () => {
                        if (ingestedPaths.has(file.path)) return;
                        setIngestedPaths((prev) => new Set(prev).add(file.path));
                        if (typeof projectApi?.addMaterialFromFile === 'function') {
                          try {
                            await projectApi.addMaterialFromFile(projectId, file.path);
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="shrink-0 rounded border border-border bg-bg-secondary px-1 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                    >
                      {ingestedPaths.has(file.path) ? '已存L4' : '+L4'}
                    </button>
                  )}
                  {projectId && (
                    <button
                      type="button"
                      data-testid={`git-sider-guard-${file.path}`}
                      onClick={async () => {
                        if (guardedPaths.has(file.path)) return;
                        setGuardedPaths((prev) => new Set(prev).add(file.path));
                        if (typeof projectApi?.createConstraint === 'function') {
                          try {
                            await projectApi.createConstraint(projectId, {
                              category: 'file_change_guard',
                              content: `关键变更文件保护规范：${file.path}`,
                              triggerPattern: file.path,
                              priority: 8,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="shrink-0 rounded border border-border bg-bg-secondary px-1 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                    >
                      {guardedPaths.has(file.path) ? '已护栏' : '+L2'}
                    </button>
                  )}
                  {projectId && (
                    <button
                      type="button"
                      data-testid={`git-sider-l3-${file.path}`}
                      onClick={async () => {
                        if (l3Paths.has(file.path)) return;
                        setL3Paths((prev) => new Set(prev).add(file.path));
                        if (typeof projectApi?.confirmKnowledge === 'function') {
                          try {
                            await projectApi.confirmKnowledge(projectId, {
                              entries: [
                                {
                                  category: 'note',
                                  content: `侧边栏 Git 变更文件 [${file.status}]：${file.path}`,
                                  importance: 6,
                                  sourceMessageIds: [],
                                  reasoning: '侧边栏 Git 变更单文件沉淀至 L3 画像',
                                },
                              ],
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="shrink-0 rounded border border-border bg-bg-secondary px-1 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                    >
                      {l3Paths.has(file.path) ? '已存L3' : '+L3'}
                    </button>
                  )}
                  {projectId && (
                    <button
                      type="button"
                      data-testid={`git-sider-milestone-${file.path}`}
                      onClick={async () => {
                        if (milestonePaths.has(file.path)) return;
                        setMilestonePaths((prev) => new Set(prev).add(file.path));
                        if (typeof projectApi?.createMilestone === 'function') {
                          try {
                            await projectApi.createMilestone(projectId, {
                              title: `[Git 变更跟进] ${file.path}`,
                              description: `侧边栏状态 [${file.status}] (${status.branch || 'HEAD'})`,
                              status: 'pending',
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="shrink-0 rounded border border-border bg-bg-secondary px-1 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                    >
                      {milestonePaths.has(file.path) ? '已建里程碑' : '+里程碑'}
                    </button>
                  )}
                  <button
                    type="button"
                    data-testid={`git-sider-copy-path-${file.path}`}
                    onClick={async () => {
                      try {
                        await navigator.clipboard?.writeText(file.path);
                        setCopiedFilePath(file.path);
                        setTimeout(() => setCopiedFilePath(null), 1500);
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="shrink-0 rounded border border-border bg-bg-secondary px-1 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                  >
                    {copiedFilePath === file.path ? '已复制' : '复制'}
                  </button>
                  <button
                    type="button"
                    data-testid={`git-sider-copy-json-${file.path}`}
                    onClick={async () => {
                      setCopiedFileJsonPath(file.path);
                      setTimeout(() => {
                        if (typeof window !== 'undefined') setCopiedFileJsonPath(null);
                      }, 1500);
                      try {
                        await navigator.clipboard?.writeText(
                          JSON.stringify(
                            {
                              path: file.path,
                              status: file.status,
                              branch: status.branch || 'HEAD',
                            },
                            null,
                            2,
                          ),
                        );
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="shrink-0 rounded border border-border bg-bg-secondary px-1 py-0.5 text-ui-2xs text-text-muted hover:text-text"
                  >
                    {copiedFileJsonPath === file.path ? '已复制JSON' : '复制JSON'}
                  </button>
                </li>
              ))}
              {filteredFiles.length > 12 && (
                <li className="text-ui-xs text-text-muted px-2 py-0.5 italic">
                  +{filteredFiles.length - 12} more
                </li>
              )}
            </ul>
          </div>
        );
      }}
    />
  );
}
