import type { BackendRequest } from '../types/electron-api';

export class BackendNotAvailableError extends Error {
  readonly code = 'BACKEND_NOT_AVAILABLE';

  constructor(message = '后端服务不可用：请使用 Sage 桌面端打开此功能') {
    super(message);
    this.name = 'BackendNotAvailableError';
  }
}

export class BackendRequestError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = 'BackendRequestError';
  }
}

/** Use the Electron main relay when available; browser fallback is fail-closed. */
export async function backendRequest<T>(request: BackendRequest): Promise<T> {
  const bridge =
    typeof window !== 'undefined' ? window.electronAPI?.backendRequest : undefined;
  if (!bridge) throw new BackendNotAvailableError();
  return bridge<T>(request);
}
