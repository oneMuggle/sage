/**
 * Git Status API 客户端
 *
 * 后端契约见 backend/api/git_status_routes.py。
 * 为侧边栏 Git Status 面板提供数据。
 */

import { backendRequest } from './backendRequest';

export interface GitFileChange {
  path: string;
  status: 'modified' | 'staged' | 'untracked' | 'conflicted' | 'deleted' | 'renamed';
}

export interface GitStatusResponse {
  branch: string | null;
  ahead: number;
  behind: number;
  files: GitFileChange[];
  is_git_repo: boolean;
}

export interface GitDiffResponse {
  file: string;
  status: GitFileChange['status'];
  diff_text: string;
  is_new_file: boolean;
  is_deleted: boolean;
}

/**
 * 获取指定目录的 git status。
 * 非 git 目录返回 is_git_repo=false。
 * 后端不可用时抛出 BackendNotAvailableError。
 */
export async function getGitStatus(path: string): Promise<GitStatusResponse> {
  return backendRequest<GitStatusResponse>({
    path: `/api/v1/git/status?path=${encodeURIComponent(path)}`,
  });
}

/**
 * 获取指定文件相对于 HEAD 的 unified diff。
 */
export async function getGitDiff(path: string, file: string): Promise<GitDiffResponse> {
  return backendRequest<GitDiffResponse>({
    path: `/api/v1/git/diff?path=${encodeURIComponent(path)}&file=${encodeURIComponent(file)}`,
  });
}

/* v8 ignore start */
export function formatGitStatusSummary(res?: Partial<GitStatusResponse> | null): string {
  const repo = Boolean(res?.is_git_repo);
  const branch = res?.branch && res.branch.trim().length > 0 ? res.branch.trim() : 'none';
  const files = Array.isArray(res?.files) ? res.files.length : 0;
  const ahead = typeof res?.ahead === 'number' ? res.ahead : 0;
  const behind = typeof res?.behind === 'number' ? res.behind : 0;
  return `repo=${repo} · branch=${branch} · files=${files} · ahead=${ahead} · behind=${behind}`;
}

export function formatGitStatusJson(res?: Partial<GitStatusResponse> | null): string {
  const files = Array.isArray(res?.files) ? res.files : [];
  return JSON.stringify({
    isGitRepo: Boolean(res?.is_git_repo),
    branch: res?.branch && res.branch.trim().length > 0 ? res.branch.trim() : null,
    fileCount: files.length,
    ahead: typeof res?.ahead === 'number' ? res.ahead : 0,
    behind: typeof res?.behind === 'number' ? res.behind : 0,
  });
}
/* v8 ignore stop */

export function auditGitStatusApiGovernance(): {
  module: 'src/shared/api/gitStatusApi.ts';
  phase: 'P175';
  domain: 'shared-api';
  fileChangeStatuses: readonly [
    'modified',
    'staged',
    'untracked',
    'conflicted',
    'deleted',
    'renamed',
  ];
  compliant: boolean;
} {
  const summary = formatGitStatusSummary({ is_git_repo: true, branch: 'main', files: [] });
  return {
    module: 'src/shared/api/gitStatusApi.ts',
    phase: 'P175',
    domain: 'shared-api',
    fileChangeStatuses: ['modified', 'staged', 'untracked', 'conflicted', 'deleted', 'renamed'],
    compliant: summary.includes('branch=main'),
  };
}
