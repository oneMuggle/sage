// src/shared/api/__tests__/fileSearchClient.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fileSearchClient } from '../fileSearchClient';

const invokeMock = vi.fn();
vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

interface FileSearchResult {
  path: string;
  name: string;
  size?: number;
}

describe('fileSearchClient', () => {
  beforeEach(() => {
    invokeMock.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('search() invokes workspace_search_files with query', async () => {
    const results: FileSearchResult[] = [
      { path: 'src/foo.ts', name: 'foo.ts' },
      { path: 'src/foo.test.ts', name: 'foo.test.ts' },
    ];
    invokeMock.mockResolvedValueOnce(results);
    const out = await fileSearchClient.search('foo');
    expect(invokeMock).toHaveBeenCalledWith('workspace_search_files', {
      query: 'foo',
      limit: 20,
    });
    expect(out).toEqual(results);
  });

  it('search() rejects with timeout error when invoke takes > 3s', async () => {
    vi.useFakeTimers();
    invokeMock.mockImplementation(() => new Promise(() => {/* never resolve */}));
    const p = fileSearchClient.search('slow');
    // Attach catch handler immediately to prevent unhandled rejection
    // eslint-disable-next-line @typescript-eslint/no-empty-function
    p.catch(() => {});
    // Advance timers FIRST, then await the rejection
    await vi.advanceTimersByTimeAsync(3001);
    await expect(p).rejects.toThrow(/timed?\s*out/i);
  });

  it('search() can be aborted via AbortSignal before timeout', async () => {
    const externalAbort = new AbortController();
    invokeMock.mockImplementation(() => new Promise<FileSearchResult[]>(() => {/* pending */}));
    const p = fileSearchClient.search('q', { signal: externalAbort.signal });
    externalAbort.abort();
    await expect(p).rejects.toThrow(/aborted/i);
  });

  it('search() respects custom limit', async () => {
    invokeMock.mockResolvedValueOnce([]);
    await fileSearchClient.search('q', { limit: 5 });
    expect(invokeMock).toHaveBeenCalledWith('workspace_search_files', {
      query: 'q',
      limit: 5,
    });
  });
});
