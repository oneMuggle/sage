import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { memoryApi } from '../memoryApi';

describe('memoryApi.getMemories response normalization', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  it('normalizes malformed envelope fields to safe defaults', async () => {
    mockInvoke.mockResolvedValue({
      items: {},
      total: -1,
      page: 0,
      page_size: -4,
      layer: 'unsupported',
      source_breakdown: { episodic: 2 },
    });

    await expect(memoryApi.getMemories()).resolves.toEqual({
      items: [],
      total: 0,
      page: 1,
      page_size: 0,
      offset: 0,
      layer: 'all',
      source_breakdown: {
        episodic: 2,
        semantic: 0,
        working: 0,
        session_summary: 0,
      },
    });
  });

  it('supports legacy flat arrays and null responses', async () => {
    mockInvoke.mockResolvedValueOnce([{ id: 'm1' }]).mockResolvedValueOnce(null);

    await expect(memoryApi.getMemories()).resolves.toMatchObject({
      items: [{ id: 'm1' }],
      total: 1,
      page: 1,
      page_size: 1,
      layer: 'all',
    });
    await expect(memoryApi.getMemories()).resolves.toEqual({
      items: [],
      total: 0,
      page: 1,
      page_size: 0,
      offset: 0,
      layer: 'all',
      source_breakdown: {
        episodic: 0,
        semantic: 0,
        working: 0,
        session_summary: 0,
      },
    });
  });

  it('clamps outgoing pagination values before invoking IPC', async () => {
    mockInvoke.mockResolvedValue({ items: [] });

    await memoryApi.getMemories('semantic', 0, 9999);

    expect(mockInvoke).toHaveBeenCalledWith('get_memories', {
      memoryType: 'semantic',
      page: 1,
      pageSize: 100,
      offset: null,
      sessionId: null,
    });
  });

  it('forwards offset + sessionId to IPC when provided', async () => {
    mockInvoke.mockResolvedValue({ items: [] });

    await memoryApi.getMemories('episodic', 2, 20, {
      offset: 40,
      sessionId: 'sess-1',
    });

    expect(mockInvoke).toHaveBeenCalledWith('get_memories', {
      memoryType: 'episodic',
      page: 2,
      pageSize: 20,
      offset: 40,
      sessionId: 'sess-1',
    });
  });
});

describe('memoryApi diagnostic formatters (Phase P113)', () => {
  it('formats memory list summary and JSON payload', async () => {
    const { formatMemoryListSummary, formatMemoryListJson } = await import('../memoryApi');
    const res = {
      items: [
        {
          id: 'm1',
          content: 'remember this',
          importance: 5,
          tags: [],
          created_at: 100,
          access_count: 1,
        },
      ],
      total: 4,
      page: 2,
      page_size: 20,
      offset: 20,
      layer: 'semantic' as const,
      source_breakdown: {
        episodic: 1,
        semantic: 3,
        working: 0,
        session_summary: 0,
      },
    };
    expect(formatMemoryListSummary(res)).toBe('semantic · 1/4 items · page 2');
    const parsed = JSON.parse(formatMemoryListJson(res));
    expect(parsed).toEqual({
      schema: 'sage.shared.memory_list.v1',
      layer: 'semantic',
      page: 2,
      pageSize: 20,
      total: 4,
      itemCount: 1,
      sourceBreakdown: {
        episodic: 1,
        semantic: 3,
        working: 0,
        session_summary: 0,
      },
    });
  });
});
