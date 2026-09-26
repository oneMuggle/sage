/**
 * Workspace Info API client.
 *
 * Fetches workspace metadata from the backend:
 * - Project name and path
 * - Git branch and status
 * - Recent file modifications
 *
 * Backend contract: backend/services/workspace_info.py
 *
 * Author: Claude
 * Date: 2026-09-26
 */

import { backendRequest } from './backendRequest';

/** Recently modified file in workspace */
export interface RecentFile {
  name: string;
  path: string;
  modified: string;
  sizeBytes: number;
}

/** Workspace information for UI display */
export interface WorkspaceInfo {
  projectName: string;
  workspacePath: string;
  gitBranch?: string | null;
  gitStatus?: string | null;
  gitAhead: number;
  gitBehind: number;
  recentFiles: RecentFile[];
  totalFiles: number;
  lastActivity?: string | null;
}

/** Fetch workspace information */
export async function getWorkspaceInfo(workspacePath: string): Promise<WorkspaceInfo> {
  const response = await backendRequest<WorkspaceInfo>({
    method: 'GET',
    path: `/api/v1/workspace/info?workspace_path=${encodeURIComponent(workspacePath)}`,
  });
  return response;
}

/** Workspace info API namespace */
export const workspaceInfoApi = {
  getInfo: getWorkspaceInfo,
};
