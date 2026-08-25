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
