// src/shared/api/fileSearchClient.ts
import { workspaceApi } from './workspaceApi';

export type FileSearchKind = 'file' | 'office-ppt' | 'office-word' | 'office-excel';

/**
 * Workspace-aware search result.
 *
 * - `path` is the managed path on disk for `kind: 'file'`, and for office
 *   kinds it is the managed path of the document under the workspace.
 * - `name` is the display name shown in the @ menu.
 * - `docId` is populated only for managed office docs (`kind !== 'file'`).
 *   Plain files always carry `docId: null`.
 * - `sourcePath` mirrors the backend `WorkspaceSearchResult.sourcePath`,
 *   non-null for office files that live outside the managed directory
 *   (i.e. the import-on-pick path — `AtFileSelection.kind === 'office-import'`).
 *
 * The shape is intentionally a superset of `WorkspaceSearchResult`. The
 * `AtFileMenu` reads `docId` + `docType` to decide whether a selection
 * becomes a managed `ChatOfficeRef` (no path round-trip) or an import flow
 * (which calls `importOfficeReference` to copy + read + finalize).
 */
export interface FileSearchResult {
  path: string;
  name: string;
  size?: number;
  kind: FileSearchKind;
  docId: string | null;
  docType: 'ppt' | 'word' | 'excel' | null;
  sourcePath: string | null;
}

export interface FileSearchOptions {
  /** 限制返回结果数, 默认 20 */
  limit?: number;
  /**
   * 外部 AbortSignal, 用于组件卸载时取消.
   *
   * `workspaceApi.search` 当前不接受 signal — 通过抛 AbortError 提前返回,
   * 让组件的 .catch 走 AbortError 分支。
   */
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

/**
 * @-menu selection — discriminated union, designed so the `ChatInput` can
 * 1. Detect whether a normal `@filename` should be inserted (file), or
 * 2. Resolve a managed Office doc by id (office), or
 * 3. Trigger an import flow via `importOfficeReference` (office-import).
 *
 * AtFileMenu MUST never fabricate a `ChatOfficeRef` for a plain file — a
 * managed office ref always has a real `docId` from the backend.
 */
export type AtFileSelection =
  | { kind: 'file'; path: string; name: string }
  | { kind: 'office-import'; result: FileSearchResult }
  | { kind: 'office'; ref: { docId: string; docType: 'ppt' | 'word' | 'excel'; filename: string } };

/**
 * Build a `ChatOfficeRef` from a workspace search result, or return `null`
 * when the result is not a managed office doc.
 *
 * - kind === 'file' → null (NEVER fabricate a ChatOfficeRef)
 * - kind === 'office-*' && needsImport === true → null (must import first)
 * - kind === 'office-*' && docId is set → returns the ref
 */
export function fileSearchResultToChatOfficeRef(
  result: FileSearchResult,
): { docId: string; docType: 'ppt' | 'word' | 'excel'; filename: string } | null {
  if (result.kind === 'file') return null;
  if (!result.docId || !result.docType) return null;
  return {
    docId: result.docId,
    docType: result.docType,
    filename: result.name,
  };
}

/**
 * Decide the selection kind for an `@`-menu item.
 *
 * - `kind: 'file'` → plain file (the menu inserts `@<path>`)
 * - office-* with `needsImport` (or missing docId) → import flow
 * - office-* with `docId` → managed ref
 */
export function classifyAtFileSelection(result: FileSearchResult): AtFileSelection['kind'] {
  if (result.kind === 'file') return 'file';
  const ref = fileSearchResultToChatOfficeRef(result);
  if (ref) return 'office';
  return 'office-import';
}

/**
 * Workspace-aware file/office search (Task 7, 2026-07-26).
 *
 * Delegates the underlying call to `workspaceApi.search(sessionId, query, limit)`.
 * The sessionId is required — without an active session the backend cannot
 * resolve a workspace binding, so we surface that as an empty result.
 *
 * Timeout (3s) is enforced client-side via Promise.race. AbortSignal
 * rejects the in-flight promise with a DOMException('aborted').
 */
export const fileSearchClient = {
  async search(
    sessionId: string,
    query: string,
    options: FileSearchOptions = {},
  ): Promise<FileSearchResult[]> {
    const limit = options.limit ?? DEFAULT_LIMIT;

    // Pre-check: external abort already fired.
    if (options.signal?.aborted) {
      throw new DOMException('aborted', 'AbortError');
    }

    if (!sessionId) {
      // No active session → empty result, mirroring the previous
      // workspacePath-short-circuit behavior. Callers (AtFileMenu)
      // already render an empty state in this case.
      return [];
    }

    const workspacePromise = workspaceApi.search(sessionId, query, limit).then((res) =>
      res.results.map<FileSearchResult>((r) => ({
        path: r.sourcePath ?? r.name,
        name: r.name,
        size: r.sizeBytes,
        kind: r.kind,
        docId: r.docId,
        docType: r.docType,
        sourcePath: r.sourcePath,
      })),
    );

    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutId = setTimeout(() => {
        reject(new FileSearchTimeoutError(query));
      }, DEFAULT_TIMEOUT_MS);
    });

    if (options.signal) {
      options.signal.addEventListener('abort', () => {
        // The promise.race winner logic + the outer `signal?.aborted`
        // check in the catch handles this case; no explicit work here.
      });
    }

    try {
      return await Promise.race([workspacePromise, timeoutPromise]);
    } catch (err) {
      if (options.signal?.aborted) {
        throw new DOMException('aborted', 'AbortError');
      }
      throw err;
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
    }
  },
};
