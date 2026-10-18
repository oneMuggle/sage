/**
 * Git 状态 Widget (2026-09-25; Phase P26 Git 状态与近期提交 Markdown 摘要一键复制 2026-10-13; Phase P32 变更文件分类过滤与一键纳入 L4 资料池 2026-10-13)
 *
 * 项目类型分类系统 - Phase 4.3 & Phase P32
 * Coding 项目专属：显示 Git 仓库状态、支持复制 Markdown 状态报告、按状态筛选变更文件并一键纳入 L4 资料池
 */

import { GitBranch, AlertCircle, CheckCircle2, Copy, Check, RefreshCw, BookmarkPlus } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';

import { projectApi } from '../../shared/api';
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
  const [filesExpanded, setFilesExpanded] = useState(false);
  const [fileFilter, setFileFilter] = useState<'all' | 'staged' | 'modified' | 'untracked'>('all');
  const [ingestedFiles, setIngestedFiles] = useState<Set<string>>(new Set());
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedSha, setCopiedSha] = useState<string | null>(null);
  const [guardedFiles, setGuardedFiles] = useState<Set<string>>(new Set());
  const [commitMilestones, setCommitMilestones] = useState<Set<string>>(new Set());
  const [commitL3Shas, setCommitL3Shas] = useState<Set<string>>(new Set());
  const [commitL4Shas, setCommitL4Shas] = useState<Set<string>>(new Set());
  const [savedCommitsL3, setSavedCommitsL3] = useState(false);
  const [savedCommitsL4, setSavedCommitsL4] = useState(false);

  const fetchStatus = useCallback(async () => {
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
  }, [projectId]);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

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

  const visibleChangedFiles = [
    ...((fileFilter === 'all' || fileFilter === 'staged') ? status.staged_files : []),
    ...((fileFilter === 'all' || fileFilter === 'modified') ? status.modified_files : []),
    ...((fileFilter === 'all' || fileFilter === 'untracked') ? status.untracked_files : []),
  ];

  const handleGuardChangedFile = async (relPath: string) => {
    if (guardedFiles.has(relPath)) return;
    setGuardedFiles((prev) => new Set(prev).add(relPath));
    if (typeof projectApi?.createConstraint === 'function') {
      try {
        await projectApi.createConstraint(projectId, {
          category: 'review_guard',
          content: `重点审查变更文件契约一致性：${relPath}`,
          triggerPattern: relPath,
          priority: 8,
        });
      } catch {
        // ignore in test/offline mode
      }
    }
  };

  const handleBatchIngestChangedFiles = async () => {
    if (typeof projectApi?.addMaterialFromFile !== 'function' || visibleChangedFiles.length === 0) {
      return;
    }
    for (const filePath of visibleChangedFiles) {
      if (ingestedFiles.has(filePath)) continue;
      try {
        await projectApi.addMaterialFromFile(projectId, filePath);
        setIngestedFiles((prev) => new Set(prev).add(filePath));
      } catch {
        // ignore in test/offline mode
      }
    }
  };

  const handleIngestChangedFile = async (filePath: string) => {
    if (ingestedFiles.has(filePath) || typeof projectApi?.addMaterialFromFile !== 'function') {
      return;
    }
    try {
      await projectApi.addMaterialFromFile(projectId, filePath);
      setIngestedFiles((prev) => new Set(prev).add(filePath));
    } catch {
      // ignore in test/offline mode
    }
  };

  const handleCopyMarkdown = () => {
    const lines = [
      `# Git 仓库状态报告 (${status.current_branch || 'HEAD'})`,
      `- **分支**: \`${status.current_branch || 'HEAD'}\``,
      `- **变更统计**: 暂存 ${status.staged_files.length} · 修改 ${status.modified_files.length} · 未跟踪 ${status.untracked_files.length}`,
    ];
    if (totalChanges > 0) {
      lines.push('', '## 变更文件明细');
      status.staged_files.forEach((f) => lines.push(`- [S] \`${f}\``));
      status.modified_files.forEach((f) => lines.push(`- [M] \`${f}\``));
      status.untracked_files.forEach((f) => lines.push(`- [U] \`${f}\``));
    }
    if (status.recent_commits.length > 0) {
      lines.push('', '## 最近提交');
      status.recent_commits.slice(0, 5).forEach((c) => {
        lines.push(`- \`${c.sha.slice(0, 7)}\` ${c.message} (${c.author}, ${c.date.split(' ')[0]})`);
      });
    }
    try {
      void navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedMd(true);
      setTimeout(() => setCopiedMd(false), 2000);
    } catch {
      // ignore clipboard errors in test/offline mode
    }
  };

  return (
    <Card data-testid="git-status-widget">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            <GitBranch className="h-4 w-4" />
            Git 状态
          </CardTitle>
          <div className="flex items-center gap-1">
            <button
              type="button"
              data-testid="git-status-copy-md-btn"
              onClick={handleCopyMarkdown}
              className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
              title="复制 Git 状态 Markdown 报告"
            >
              {copiedMd ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
              {copiedMd ? '已复制' : '复制报告'}
            </button>
            <button
              type="button"
              data-testid="git-status-refresh-btn"
              onClick={() => void fetchStatus()}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              title="刷新 Git 状态"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
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
            <button
              type="button"
              data-testid="git-status-files-toggle"
              onClick={() => setFilesExpanded((v) => !v)}
              className="mt-1 text-xs font-medium text-primary hover:underline"
            >
              {filesExpanded ? '收起变更文件明细' : `展开变更文件 (${totalChanges})`}
            </button>
            {filesExpanded && (
              <div className="mt-1 space-y-1.5" data-testid="git-status-files-list">
                <div className="flex flex-wrap items-center gap-1">
                  {(
                    [
                      { key: 'all', label: `全部 (${totalChanges})` },
                      { key: 'staged', label: `暂存 (${status.staged_files.length})` },
                      { key: 'modified', label: `修改 (${status.modified_files.length})` },
                      { key: 'untracked', label: `未跟踪 (${status.untracked_files.length})` },
                    ] as const
                  ).map((tab) => (
                    <button
                      key={tab.key}
                      type="button"
                      data-testid={`git-widget-filter-${tab.key}`}
                      onClick={() => setFileFilter(tab.key)}
                      className={`rounded px-1.5 py-0.5 text-ui-2xs transition-colors ${
                        fileFilter === tab.key
                          ? 'bg-primary text-primary-foreground font-medium'
                          : 'bg-muted/60 text-muted-foreground hover:bg-muted'
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                  {visibleChangedFiles.length > 0 && (
                    <div className="ml-auto flex items-center gap-1">
                    <button
                      type="button"
                      data-testid="git-widget-guard-all-btn"
                      onClick={async () => {
                        for (const filePath of visibleChangedFiles) {
                          await handleGuardChangedFile(filePath);
                        }
                      }}
                      className="inline-flex items-center gap-0.5 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs font-medium text-foreground hover:bg-muted"
                    >
                      批量护栏 L2 ({visibleChangedFiles.length})
                    </button>
                    <button
                      type="button"
                      data-testid="git-widget-ingest-all-btn"
                      onClick={() => void handleBatchIngestChangedFiles()}
                      className="inline-flex items-center gap-0.5 rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 text-ui-2xs font-medium text-primary hover:bg-primary/10"
                    >
                      <BookmarkPlus className="h-2.5 w-2.5" />
                      批量纳入 L4 ({visibleChangedFiles.length})
                    </button>
                    </div>
                  )}
                </div>
                <div className="max-h-32 overflow-y-auto rounded border border-border bg-muted/30 p-1.5 font-mono text-ui-2xs space-y-1">
                  {(fileFilter === 'all' || fileFilter === 'staged') &&
                    status.staged_files.map((f) => (
                      <div
                        key={`s:${f}`}
                        className="flex items-center justify-between gap-2 text-green-600 dark:text-green-400"
                      >
                        <span className="truncate">[S] {f}</span>
                        <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          data-testid={`git-widget-guard-${f}`}
                          onClick={() => void handleGuardChangedFile(f)}
                          className="rounded border border-border bg-background px-1 py-0.2 text-ui-2xs font-sans text-primary hover:bg-primary/10"
                        >
                          {guardedFiles.has(f) ? '已护栏' : '+L2'}
                        </button>
                        <button
                          type="button"
                          data-testid={`git-widget-ingest-${f}`}
                          onClick={() => void handleIngestChangedFile(f)}
                          className="shrink-0 inline-flex items-center gap-0.5 rounded border border-border bg-background px-1 py-0.2 text-ui-2xs font-sans text-muted-foreground hover:text-foreground"
                        >
                          <BookmarkPlus className="h-2.5 w-2.5" />
                          {ingestedFiles.has(f) ? '已纳入 L4' : '+L4'}
                        </button>
                        </div>
                      </div>
                    ))}
                  {(fileFilter === 'all' || fileFilter === 'modified') &&
                    status.modified_files.map((f) => (
                      <div
                        key={`m:${f}`}
                        className="flex items-center justify-between gap-2 text-orange-600 dark:text-orange-400"
                      >
                        <span className="truncate">[M] {f}</span>
                        <button
                          type="button"
                          data-testid={`git-widget-ingest-${f}`}
                          onClick={() => void handleIngestChangedFile(f)}
                          className="shrink-0 inline-flex items-center gap-0.5 rounded border border-border bg-background px-1 py-0.2 text-ui-2xs font-sans text-muted-foreground hover:text-foreground"
                        >
                          <BookmarkPlus className="h-2.5 w-2.5" />
                          {ingestedFiles.has(f) ? '已纳入 L4' : '+L4'}
                        </button>
                      </div>
                    ))}
                  {(fileFilter === 'all' || fileFilter === 'untracked') &&
                    status.untracked_files.map((f) => (
                      <div
                        key={`u:${f}`}
                        className="flex items-center justify-between gap-2 text-muted-foreground"
                      >
                        <span className="truncate">[U] {f}</span>
                        <button
                          type="button"
                          data-testid={`git-widget-ingest-${f}`}
                          onClick={() => void handleIngestChangedFile(f)}
                          className="shrink-0 inline-flex items-center gap-0.5 rounded border border-border bg-background px-1 py-0.2 text-ui-2xs font-sans text-muted-foreground hover:text-foreground"
                        >
                          <BookmarkPlus className="h-2.5 w-2.5" />
                          {ingestedFiles.has(f) ? '已纳入 L4' : '+L4'}
                        </button>
                      </div>
                    ))}
                </div>
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
            <div className="mb-1 flex items-center justify-between gap-2">
              <div className="text-xs text-muted-foreground">最近提交</div>
              <button
                type="button"
                data-testid="git-widget-save-commits-l3-btn"
                onClick={async () => {
                  if (savedCommitsL3) return;
                  setSavedCommitsL3(true);
                  if (typeof projectApi?.confirmKnowledge === 'function') {
                    try {
                      await projectApi.confirmKnowledge(projectId, {
                        entries: [
                          {
                            category: 'note',
                            content: `Git 最近提交摘要 (${status.current_branch})：${status.recent_commits.slice(0, 3).map((c) => `${c.sha.slice(0, 7)} ${c.message}`).join('；')}`,
                            importance: 6,
                            sourceMessageIds: [],
                            reasoning: 'Git 最近提交沉淀至 L3 画像',
                          },
                        ],
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
              >
                {savedCommitsL3 ? '已沉淀至 L3' : '沉淀提交摘要至 L3'}
              </button>
              <button
                type="button"
                data-testid="git-widget-save-l4-btn"
                onClick={async () => {
                  if (savedCommitsL4) return;
                  setSavedCommitsL4(true);
                  if (typeof projectApi?.addMaterial === 'function') {
                    try {
                      await projectApi.addMaterial(projectId, {
                        content: `# Git 最近提交记录 (${status.current_branch ?? 'default'})\n${status.recent_commits
                          .slice(0, 5)
                          .map((c) => `- \`${c.sha.slice(0, 7)}\` ${c.message} (${c.author})`)
                          .join('\n')}`,
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
              >
                {savedCommitsL4 ? '已存提交至 L4' : '存提交至 L4'}
              </button>
            </div>
            <div className="space-y-1">
              {status.recent_commits.slice(0, 3).map((commit) => (
                <div key={commit.sha} className="text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium truncate">{commit.message}</div>
                    <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      data-testid={`git-widget-commit-to-milestone-${commit.sha}`}
                      onClick={async () => {
                        if (commitMilestones.has(commit.sha)) return;
                        setCommitMilestones((prev) => new Set(prev).add(commit.sha));
                        if (typeof projectApi?.createMilestone === 'function') {
                          try {
                            await projectApi.createMilestone(projectId, {
                              title: `[Git ${commit.sha.slice(0, 7)}] ${commit.message.slice(0, 70)}`,
                              description: `提交作者: ${commit.author} · 日期: ${commit.date}`,
                              status: 'completed',
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-muted/40 px-1 py-0.2 text-ui-2xs text-muted-foreground hover:text-foreground"
                    >
                      {commitMilestones.has(commit.sha) ? '已建里程碑' : '+里程碑'}
                    </button>
                    <button
                      type="button"
                      data-testid={`git-widget-commit-to-l3-${commit.sha}`}
                      onClick={async () => {
                        if (commitL3Shas.has(commit.sha)) return;
                        setCommitL3Shas((prev) => new Set(prev).add(commit.sha));
                        if (typeof projectApi?.confirmKnowledge === 'function') {
                          try {
                            await projectApi.confirmKnowledge(projectId, {
                              entries: [
                                {
                                  category: 'decision',
                                  content: `Git 提交记录 [${commit.sha.slice(0, 7)}]：${commit.message} (${commit.author})`,
                                  importance: 7,
                                  sourceMessageIds: [],
                                  reasoning: 'Git 单条提交记录沉淀至 L3 画像',
                                },
                              ],
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-muted/40 px-1 py-0.2 text-ui-2xs text-muted-foreground hover:text-foreground"
                    >
                      {commitL3Shas.has(commit.sha) ? '已存L3' : '+L3'}
                    </button>
                    <button
                      type="button"
                      data-testid={`git-widget-commit-to-l4-${commit.sha}`}
                      onClick={async () => {
                        if (commitL4Shas.has(commit.sha)) return;
                        setCommitL4Shas((prev) => new Set(prev).add(commit.sha));
                        if (typeof projectApi?.addMaterial === 'function') {
                          try {
                            await projectApi.addMaterial(projectId, {
                              content: `# Git 提交记录 [${commit.sha.slice(0, 7)}]\n- 作者: ${commit.author}\n- 时间: ${commit.date}\n\n${commit.message}`,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-muted/40 px-1 py-0.2 text-ui-2xs text-muted-foreground hover:text-foreground"
                    >
                      {commitL4Shas.has(commit.sha) ? '已存L4' : '+L4'}
                    </button>
                    <button
                      type="button"
                      data-testid={`git-widget-copy-sha-${commit.sha}`}
                      onClick={async () => {
                        try {
                          await navigator.clipboard?.writeText(commit.sha);
                          setCopiedSha(commit.sha);
                          setTimeout(() => setCopiedSha(null), 1500);
                        } catch {
                          // ignore in test/offline mode
                        }
                      }}
                      className="shrink-0 rounded border border-border bg-muted/40 px-1 py-0.2 font-mono text-ui-2xs text-muted-foreground hover:text-foreground"
                      title="复制提交 SHA"
                    >
                      {copiedSha === commit.sha ? '已复制' : commit.sha.slice(0, 7)}
                    </button>
                    </div>
                  </div>
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
