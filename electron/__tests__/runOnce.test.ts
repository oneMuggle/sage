import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockCalls: Array<{ cmd: string; args: string[] }> = [];

vi.mock('child_process', () => {
  const spawn = vi.fn((cmd: string, args: string[]) => {
    mockCalls.push({ cmd, args });
    return {
      on: (_event: string, cb: () => void) => cb(),
      unref: vi.fn(),
    };
  });
  return {
    default: { spawn },
    spawn,
  };
});

import { clearRunOnce, registerRunOnceCommand } from '../update/runOnce';

describe('runOnce (Windows RunOnce 注册表助手)', () => {
  beforeEach(() => {
    mockCalls.length = 0;
  });

  it('registerRunOnceCommand 以 reg add HKCU RunOnce 写入指定命令', async () => {
    await registerRunOnceCommand('cmd /c "C:/bat-dir/.prepare-rollback.bat"');
    expect(mockCalls).toHaveLength(1);
    expect(mockCalls[0].cmd).toBe('reg');
    expect(mockCalls[0].args[0]).toBe('add');
    expect(mockCalls[0].args[1]).toContain('RunOnce');
    expect(mockCalls[0].args[3]).toBe('SageRollback');
    expect(mockCalls[0].args[7]).toContain('.prepare-rollback.bat');
  });

  it('clearRunOnce 以 reg delete 清除 SageRollback', async () => {
    await clearRunOnce();
    expect(mockCalls).toHaveLength(1);
    expect(mockCalls[0].args[0]).toBe('delete');
    expect(mockCalls[0].args[3]).toBe('SageRollback');
  });

  it('spawn 抛错时 resolve 而不 reject (best-effort 契约)', async () => {
    const spawnMock = vi.fn(() => {
      throw new Error('spawn boom');
    });
    const cp = (await import('child_process')) as unknown as {
      spawn: typeof spawnMock;
    };
    cp.spawn = spawnMock as unknown as typeof cp.spawn;
    await expect(registerRunOnceCommand('anything')).resolves.toBeUndefined();
  });
});
