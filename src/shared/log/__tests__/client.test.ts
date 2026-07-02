// src/shared/log/__tests__/client.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';

beforeEach(() => {
  delete (globalThis as unknown as { window?: unknown }).window;
  vi.resetModules();
});

describe('clientLogger', () => {
  it('no-ops when window.electronAPI.log is unavailable', async () => {
    const { clientLogger } = await import('../client');
    expect(() => {
      clientLogger.info('test');
      clientLogger.error('test', { foo: 'bar' });
    }).not.toThrow();
  });

  it('forwards to window.electronAPI.log without awaiting', async () => {
    const mockLog = vi.fn().mockResolvedValue({ ok: true });
    (globalThis as unknown as { window: { electronAPI: { log: typeof mockLog } } }).window = {
      electronAPI: { log: mockLog },
    };
    vi.resetModules();

    const { clientLogger } = await import('../client');
    clientLogger.warn('something', { code: 42 });

    await Promise.resolve();
    expect(mockLog).toHaveBeenCalledWith('warn', 'something', { code: 42 });
  });

  it('silently swallows IPC errors', async () => {
    const mockLog = vi.fn().mockRejectedValue(new Error('IPC failed'));
    (globalThis as unknown as { window: { electronAPI: { log: typeof mockLog } } }).window = {
      electronAPI: { log: mockLog },
    };
    vi.resetModules();

    const { clientLogger } = await import('../client');
    expect(() => clientLogger.error('oops')).not.toThrow();

    await new Promise((r) => setTimeout(r, 0));
    expect(mockLog).toHaveBeenCalled();
  });
});
