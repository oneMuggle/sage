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
