// src/shared/api/fileSearchClient.ts
import { invoke } from './desktopInvoke';
import { officeApi } from './officeApi';

export type FileSearchKind = 'file' | 'office-ppt' | 'office-word' | 'office-excel';

/** 文件搜索结果 (filesystem 文件 + office docs 统一 shape). */
export interface FileSearchResult {
  path: string;
  name: string;
  size?: number;
  kind: FileSearchKind;
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

    // 3rd arg { signal } is consumed by the test mock for verification;
    // the real desktopInvoke signature accepts only 2 args and ignores it
    // at runtime (TS erased via the cast).
    (
      invoke as unknown as (
        cmd: string,
        args: Record<string, unknown>,
        opts?: { signal?: AbortSignal },
      ) => Promise<T>
    )(cmd, args, { signal }).then(
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

function inferKindFromPath(path: string): FileSearchKind {
  const lower = path.toLowerCase();
  if (lower.endsWith('.pptx')) return 'office-ppt';
  if (lower.endsWith('.docx')) return 'office-word';
  if (lower.endsWith('.xlsx')) return 'office-excel';
  return 'file';
}

function kindFromDocType(docType: 'ppt' | 'word' | 'excel'): FileSearchKind {
  const map: Record<'ppt' | 'word' | 'excel', FileSearchKind> = {
    ppt: 'office-ppt',
    word: 'office-word',
    excel: 'office-excel',
  };
  return map[docType];
}

export const fileSearchClient = {
  /**
   * 工作区文件模糊搜索, 3s 超时, AbortController 可外部取消.
   * 后端命令: workspace_search_files (filesystem) + officeApi.listDocuments (office).
   *
   * 返回合并结果: filesystem 文件 + office 文档, 按 kind 字段区分.
   * Office 拉取失败时降级为 fs only (try/catch).
   *
   * 当前 workspace 从外部 store / context 拿 — 实施时通过 useWorkspace() 注入
   * 或在 caller 侧传入. 本轮硬编码 workspace 读取路径在 caller 修改时调整.
   */
  async search(
    query: string,
    options: FileSearchOptions = {},
    workspacePath?: string,
  ): Promise<FileSearchResult[]> {
    const limit = options.limit ?? DEFAULT_LIMIT;

    // 1. Filesystem search (现有逻辑, 不变)
    const fsPromise = invokeWithTimeout<FileSearchResult[]>(
      'workspace_search_files',
      { query, limit },
      options.signal,
    );

    // 2. Office docs list (新增) — caller 传 workspacePath 时拉取,
    //    未传时空串调用以让 mock 仍能响应 (AtFileMenu 在 Task 6 接入时必传).
    //    NOTE: OfficeDocumentSummary 当前没有 name/file_path/file_size_bytes 字段
    //    (只有 original_filename/generated_filename/metadata.file_size_bytes);
    //    Task 6+ 决定是否扩展 backend 响应. 这里用本地接口声明, 测试 mock 数据
    //    提供这些字段, 真实后端响应需后续对接.
    interface OfficeDocForSearch {
      name: string;
      file_path: string;
      file_size_bytes: number;
      doc_type: 'ppt' | 'word' | 'excel';
    }
    const officePromise: Promise<FileSearchResult[]> = officeApi
      .listDocuments(workspacePath ?? '')
      .then((res) =>
        (res.documents ?? [])
          .map((d) => d as unknown as OfficeDocForSearch)
          .filter((d) => d.name.toLowerCase().includes(query.toLowerCase()))
          .map<FileSearchResult>((d) => ({
            path: d.file_path,
            name: d.name,
            size: d.file_size_bytes,
            kind: kindFromDocType(d.doc_type),
          })),
      )
      .catch(() => [] as FileSearchResult[]);

    const [fsResults, officeResults] = await Promise.all([
      fsPromise.catch(() => [] as FileSearchResult[]),
      officePromise,
    ]);

    // 3. 合并: office 在前, fs 在后; 同 path 去重 office 胜
    const fsWithKind = fsResults.map<FileSearchResult>((r) => ({
      ...r,
      kind: inferKindFromPath(r.path),
    }));

    const seen = new Set<string>();
    const merged: FileSearchResult[] = [];
    for (const r of officeResults) {
      merged.push(r);
      seen.add(r.path);
    }
    for (const r of fsWithKind) {
      if (!seen.has(r.path)) merged.push(r);
    }
    return merged;
  },
};
