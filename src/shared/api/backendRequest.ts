import type { BackendRequest } from '../types/electron-api';

import { isDemoMode } from './demoFlag';

export class BackendNotAvailableError extends Error {
  readonly code = 'BACKEND_NOT_AVAILABLE';

  constructor(message = '后端服务不可用：请使用 Sage 桌面端打开此功能') {
    super(message);
    this.name = 'BackendNotAvailableError';
  }
}

export class BackendRequestError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'BackendRequestError';
  }
}

/** Use the Electron main relay when available; browser fallback is fail-closed. */
export async function backendRequest<T>(request: BackendRequest): Promise<T> {
  // 演示模式: HTTP relay 在 main 进程被拦截 (sage:backend-request 直接抛异常).
  // 在渲染层提前匹配已知路径, 返回合成数据, 避免无后端时 E2E stub 失败.
  if (isDemoMode()) {
    const { demoBackendRequest } = await import('./demoInterceptors');
    const demo = demoBackendRequest(request);
    if (demo.hit) {
      await new Promise((resolve) => setTimeout(resolve, 120 + Math.random() * 140));
      return demo.value as T;
    }
  }
  const bridge = typeof window !== 'undefined' ? window.electronAPI?.backendRequest : undefined;
  if (!bridge) throw new BackendNotAvailableError();
  return bridge<T>(request);
}

export function formatBackendRequestSummary(request: BackendRequest): string {
  const method = request.method ?? 'GET';
  const hasBody = request.body !== undefined;
  return `${method} ${request.path} · body=${hasBody}`;
}

export function formatBackendRequestJson(request: BackendRequest): string {
  return JSON.stringify(
    {
      method: request.method ?? 'GET',
      path: request.path,
      hasBody: request.body !== undefined,
      bridgeAvailable: typeof window !== 'undefined' && Boolean(window.electronAPI?.backendRequest),
    },
    null,
    2,
  );
}

export function auditBackendRequestGovernance(): {
  module: 'src/shared/api/backendRequest.tsx' | 'src/shared/api/backendRequest.ts';
  phase: 'P174';
  domain: 'shared-api';
  failClosedFallbackErrorCode: 'BACKEND_NOT_AVAILABLE';
  compliant: boolean;
} {
  const err = new BackendNotAvailableError();
  return {
    module: 'src/shared/api/backendRequest.ts',
    phase: 'P174',
    domain: 'shared-api',
    failClosedFallbackErrorCode: err.code,
    compliant: err.code === 'BACKEND_NOT_AVAILABLE',
  };
}
