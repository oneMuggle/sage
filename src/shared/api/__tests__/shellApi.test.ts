// shellApi 客户端测试（2026-11-06 Phase 3）
import { beforeEach, describe, expect, it, vi } from 'vitest';

const invokeMock = vi.fn();
vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

const listenMock = vi.fn();
vi.mock('../desktopEvent', () => ({
  listen: (...args: unknown[]) => listenMock(...args),
}));

import { listShells, listenShellStream } from '../shellApi';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('listShells', () => {
  it('unwraps the shells array', async () => {
    invokeMock.mockResolvedValue({
      shells: [
        {
          shell_id: 'sh-1',
          command: 'pytest -q',
          status: 'running',
          pid: 123,
          age_seconds: 5,
        },
      ],
    });
    const shells = await listShells();
    expect(invokeMock).toHaveBeenCalledWith('shell_list');
    expect(shells).toHaveLength(1);
    expect(shells[0].shell_id).toBe('sh-1');
  });

  it('falls back to empty array on unexpected payload', async () => {
    invokeMock.mockResolvedValue(null);
    expect(await listShells()).toEqual([]);
  });
});

describe('listenShellStream', () => {
  it('subscribes with the shell-stream event name and unwraps payload', async () => {
    const unlisten = vi.fn();
    const handler = vi.fn();
    listenMock.mockImplementation(async (_event: string, cb: (e: unknown) => void) => {
      cb({ payload: { type: 'output', stream: 'stdout', data: 'hi' } });
      return unlisten;
    });
    const unsubscribe = await listenShellStream('sh-1', handler);
    expect(listenMock).toHaveBeenCalledWith(
      'shell-stream-sh-1',
      expect.any(Function),
      { streamId: 'sh-1' },
    );
    expect(handler).toHaveBeenCalledWith({
      type: 'output',
      stream: 'stdout',
      data: 'hi',
    });
    expect(unsubscribe).toBe(unlisten);
  });
});
