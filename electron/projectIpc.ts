/**
 * Project folder IPC (2026-10-29).
 *
 * The renderer only ever passes a registered project id. The main process
 * resolves the real path from the backend (`GET /projects/{id}/location`),
 * validates it is an existing directory, then opens/reveals it through
 * Electron's shell. No raw renderer-supplied path is ever accepted.
 */
import { isAbsolute } from 'node:path';

export type ProjectIpcResult = { success: true } | { error: string };

export interface ProjectIpcDeps {
  register: (channel: string, handler: (event: unknown, payload?: unknown) => unknown) => void;
  fetch: (
    url: string,
    init?: { headers?: Record<string, string> },
  ) => Promise<{ ok: boolean; status: number; json: () => Promise<unknown> }>;
  shell: {
    openPath(path: string): Promise<string>;
    showItemInFolder(path: string): void;
  };
  isDirectory: (path: string) => boolean;
  isTrusted: (sender: unknown) => boolean;
  backendUrl: string;
  getToken: () => string | null;
}

interface LocationPayload {
  projectId?: unknown;
}

async function resolveProjectPath(
  deps: ProjectIpcDeps,
  payload: LocationPayload | undefined,
): Promise<{ path: string } | { error: string }> {
  const projectId = typeof payload?.projectId === 'string' ? payload.projectId : '';
  if (!projectId) return { error: '缺少 projectId' };

  const token = deps.getToken();
  let response: Awaited<ReturnType<ProjectIpcDeps['fetch']>>;
  try {
    response = await deps.fetch(
      `${deps.backendUrl}/api/v1/projects/${encodeURIComponent(projectId)}/location`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
  } catch {
    return { error: '无法连接本地后端服务' };
  }
  if (!response.ok) {
    return {
      error:
        response.status === 410
          ? '项目目录不存在或已被移动'
          : `查询项目路径失败 (HTTP ${response.status})`,
    };
  }
  const data = (await response.json()) as { path?: unknown };
  const path = typeof data.path === 'string' ? data.path : '';
  if (!path || !isAbsolute(path) || !deps.isDirectory(path)) {
    return { error: '项目目录不存在或已被移动' };
  }
  return { path };
}

export function registerProjectIpc(deps: ProjectIpcDeps): void {
  deps.register('project:open-folder', async (event, payload) => {
    if (!deps.isTrusted(event)) return { error: '未授权的窗口请求' } satisfies ProjectIpcResult;
    const resolved = await resolveProjectPath(deps, payload as LocationPayload);
    if ('error' in resolved) return resolved satisfies ProjectIpcResult;
    const openError = await deps.shell.openPath(resolved.path);
    return openError
      ? ({ error: `打开失败：${openError}` } satisfies ProjectIpcResult)
      : ({ success: true } satisfies ProjectIpcResult);
  });

  deps.register('project:reveal-folder', async (event, payload) => {
    if (!deps.isTrusted(event)) return { error: '未授权的窗口请求' } satisfies ProjectIpcResult;
    const resolved = await resolveProjectPath(deps, payload as LocationPayload);
    if ('error' in resolved) return resolved satisfies ProjectIpcResult;
    deps.shell.showItemInFolder(resolved.path);
    return { success: true } satisfies ProjectIpcResult;
  });
}
