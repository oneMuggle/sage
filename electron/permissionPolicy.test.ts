// electron/permissionPolicy.test.ts
//
// 默认拒绝权限策略测试：验证白名单权限放行，其余拒绝。
// 挂在 default session 上，避免覆盖 agentBrowserHost / browserPanel 各自
// partition 的"全部拒绝"策略。
import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('installPermissionPolicy', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('拒绝 geolocation/camera/microphone', async () => {
    const mockSession = {
      setPermissionRequestHandler: vi.fn(),
      setPermissionCheckHandler: vi.fn(),
    };
    vi.doMock('electron', () => ({ session: { defaultSession: mockSession } }));

    const { installPermissionPolicy } = await import('./permissionPolicy');
    installPermissionPolicy();

    const reqHandler = mockSession.setPermissionRequestHandler.mock.calls[0][0];
    const checkHandler = mockSession.setPermissionCheckHandler.mock.calls[0][0];

    const reqCb = vi.fn();
    reqHandler({}, 'geolocation', reqCb);
    expect(reqCb).toHaveBeenCalledWith(false);

    // setPermissionCheckHandler 直接返回 boolean（非回调形式）
    expect(checkHandler({}, 'camera', 'https://example.com')).toBe(false);

    const reqCb2 = vi.fn();
    reqHandler({}, 'microphone', reqCb2);
    expect(reqCb2).toHaveBeenCalledWith(false);
  });

  it('放行 clipboard-read/clipboard-sanitized-write/notifications', async () => {
    const mockSession = {
      setPermissionRequestHandler: vi.fn(),
      setPermissionCheckHandler: vi.fn(),
    };
    vi.doMock('electron', () => ({ session: { defaultSession: mockSession } }));

    const { installPermissionPolicy } = await import('./permissionPolicy');
    installPermissionPolicy();

    const reqHandler = mockSession.setPermissionRequestHandler.mock.calls[0][0];
    const checkHandler = mockSession.setPermissionCheckHandler.mock.calls[0][0];

    for (const perm of ['clipboard-read', 'clipboard-sanitized-write', 'notifications']) {
      const reqCb = vi.fn();
      reqHandler({}, perm, reqCb);
      expect(reqCb).toHaveBeenCalledWith(true);

      expect(checkHandler({}, perm, 'https://example.com')).toBe(true);
    }
  });
});
