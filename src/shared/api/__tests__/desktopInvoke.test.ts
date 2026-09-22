/**
 * r99: desktopInvoke 单测——demo 分支、错误漏斗（status_code 提取 /
 * BackendNotReady 直通 / 后端断开友好翻译）与普通透传。
 *
 * 已有 test_desktop_invoke_econnrefused.test.ts 覆盖 ECONNREFUSED 主路径；
 * 本文件补齐其余分支。demoFlag/demoInterceptors 以 vi.mock 替身注入。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({
  demoMode: false,
  demoHit: true,
  demoValue: { ok: 1 } as unknown,
  demoCalls: [] as Array<{ cmd: string; args: Record<string, unknown> }>,
}));

vi.mock('../demoFlag', () => ({
  isDemoMode: () => state.demoMode,
}));

vi.mock('../demoInterceptors', () => ({
  demoInvoke: (cmd: string, args: Record<string, unknown>) => {
    state.demoCalls.push({ cmd, args });
    return { hit: state.demoHit, value: state.demoValue };
  },
}));

import { invoke } from '../desktopInvoke';

function stubApi(invokeImpl: () => Promise<unknown> | unknown) {
  const apiInvoke = vi.fn(invokeImpl);
  vi.stubGlobal('window', { electronAPI: { invoke: apiInvoke } });
  return apiInvoke;
}

beforeEach(() => {
  state.demoMode = false;
  state.demoHit = true;
  state.demoValue = { ok: 1 };
  state.demoCalls = [];
  vi.unstubAllGlobals();
});

describe('invoke demo 分支', () => {
  it('demo 命中：返回合成数据且不走 electronAPI', async () => {
    state.demoMode = true;
    const apiInvoke = stubApi(() => Promise.reject(new Error('should not be called')));
    const r = await invoke('sessions_list', { a: 1 });
    expect(r).toEqual({ ok: 1 });
    expect(state.demoCalls[0]).toEqual({ cmd: 'sessions_list', args: { a: 1 } });
    expect(apiInvoke).not.toHaveBeenCalled();
  }, 10_000);

  it('demo 未命中通道：抛固定错误', async () => {
    state.demoMode = true;
    state.demoHit = false;
    await expect(invoke('projects_register', {})).rejects.toThrow('演示模式不支持该后端操作');
  });
});

describe('invoke 真实通道', () => {
  it('无 electronAPI 抛可读错误', async () => {
    await expect(invoke('x')).rejects.toThrow('electronAPI not available');
  });

  it('成功透传；args 缺省补空对象', async () => {
    const apiInvoke = stubApi(() => Promise.resolve({ fine: true }));
    await expect(invoke('cmd_a')).resolves.toEqual({ fine: true });
    expect(apiInvoke).toHaveBeenCalledWith('cmd_a', {});
  });
});

describe('invoke 错误漏斗', () => {
  it('message 含 "→ 404:" 时附加 status_code=404 且保留原 message', async () => {
    stubApi(() => Promise.reject(new Error('GET /x → 404: Not Found')));
    const err = (await invoke('cmd_a').catch((e) => e)) as Error & {
      status_code?: number;
    };
    expect(err.status_code).toBe(404);
    expect(err.message).toContain('404: Not Found');
  });

  it('后端未就绪标记原样透传（不被断网文案改写）', async () => {
    const msg = '后端服务尚未就绪，正在启动…';
    stubApi(() => Promise.reject(new Error(msg)));
    await expect(invoke('cmd_a')).rejects.toThrow(msg);
  });

  it('ECONNREFUSED 翻译为中文友好提示', async () => {
    stubApi(() => Promise.reject(new Error('connect ECONNREFUSED 127.0.0.1:8765')));
    await expect(invoke('cmd_a')).rejects.toThrow('后端服务未启动或已断开');
  });

  it('fetch failed 同样翻译', async () => {
    stubApi(() => Promise.reject(new Error('TypeError: fetch failed')));
    await expect(invoke('cmd_a')).rejects.toThrow('后端服务未启动或已断开');
  });

  it('普通业务错误（无标记）原样抛出', async () => {
    stubApi(() => Promise.reject(new Error('validation failed /validation/name')));
    await expect(invoke('cmd_a')).rejects.toThrow('validation failed /validation/name');
  });

  it('非 Error 拒绝包装为 Error', async () => {
    stubApi(() => Promise.reject('plain string failure'));
    await expect(invoke('cmd_a')).rejects.toThrow('plain string failure');
  });
});
