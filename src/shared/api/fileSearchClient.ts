// src/shared/api/fileSearchClient.ts
import { invoke } from './desktopInvoke';

/** 文件搜索结果 (与后端 workspace_search_files 响应一致) */
export interface FileSearchResult {
  path: string;
  name: string;
  size?: number;
}

export interface FileSearchOptions {
  /** 限制返回结果数, 默认 20 */
  limit?: number;
  /** 外部 AbortSignal, 用于组件卸载时取消 */
  signal?: AbortSignal;
}

const DEFAULT_TIMEOUT_MS = 3000;
const DEFAULT_LIMIT = 20;

export class FileSearchTimeoutError extends Error {
  constructor(public readonly query: string) {
    super(`File search timed out after ${DEFAULT_TIMEOUT_MS}ms for query: ${query}`);
    this.name = 'FileSearchTimeoutError';
  }
}

async function invokeWithTimeout<T>(
  cmd: string,
  args: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  if (signal?.aborted) {
    throw new DOMException('aborted', 'AbortError');
  }

  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const settle = (): boolean => {
      if (settled) return false;
      settled = true;
      return true;
    };

    const timeoutId = setTimeout(() => {
      if (settle()) {
        cleanup();
        reject(new FileSearchTimeoutError(String(args.query ?? '')));
      }
    }, DEFAULT_TIMEOUT_MS);

    const onExternalAbort = (): void => {
      if (settle()) {
        cleanup();
        reject(new DOMException('aborted', 'AbortError'));
      }
    };

    const cleanup = (): void => {
      clearTimeout(timeoutId);
      signal?.removeEventListener('abort', onExternalAbort);
    };

    signal?.addEventListener('abort', onExternalAbort);

    invoke<T>(cmd, args).then(
      (result) => {
        if (settle()) {
          cleanup();
          resolve(result);
        }
      },
      (err) => {
        if (settle()) {
          cleanup();
          reject(err);
        }
      },
    );
  });
}

export const fileSearchClient = {
  /**
   * 工作区文件模糊搜索, 3s 超时, AbortController 可外部取消
   * 后端命令: workspace_search_files (Phase 6 由后端实现, 此处仅前端桩化测试)
   */
  async search(
    query: string,
    options: FileSearchOptions = {},
  ): Promise<FileSearchResult[]> {
    const limit = options.limit ?? DEFAULT_LIMIT;
    return invokeWithTimeout<FileSearchResult[]>(
      'workspace_search_files',
      { query, limit },
      options.signal,
    );
  },
};
