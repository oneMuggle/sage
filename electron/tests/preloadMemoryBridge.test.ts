import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('preload memory bridge', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('exposes memory methods that forward through sage:invoke', async () => {
    const invoke = vi.fn().mockResolvedValue({ status: 'ok' });
    const expose = vi.fn();
    vi.doMock('electron', () => ({
      contextBridge: { exposeInMainWorld: expose },
      ipcRenderer: { invoke, on: vi.fn(), off: vi.fn() },
    }));

    await import('../preload');
    const api = expose.mock.calls[0]?.[1] as {
      memory: {
        list: (args: Record<string, unknown>) => Promise<unknown>;
        save: (args: Record<string, unknown>) => Promise<unknown>;
        diagnostics: () => Promise<unknown>;
      };
    };

    await api.memory.list({ page: 1, pageSize: 100 });
    await api.memory.save({ content: 'prefers dark mode' });
    await api.memory.diagnostics();

    expect(invoke.mock.calls).toEqual([
      ['sage:invoke', { cmd: 'get_memories', args: { page: 1, pageSize: 100 } }],
      ['sage:invoke', { cmd: 'save_memory', args: { content: 'prefers dark mode' } }],
      ['sage:invoke', { cmd: 'get_memory_diagnostics', args: {} }],
    ]);
  });
});
