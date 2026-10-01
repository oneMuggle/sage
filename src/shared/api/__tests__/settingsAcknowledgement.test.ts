import { afterEach, describe, expect, it, vi } from 'vitest';

const { mockInvoke } = vi.hoisted(() => ({ mockInvoke: vi.fn() }));
vi.mock('../desktopInvoke', () => ({ invoke: mockInvoke }));
import { settingsClient } from '../settingsClient';

afterEach(() => {
  mockInvoke.mockReset();
  vi.restoreAllMocks();
});

describe('settings write acknowledgements', () => {
  it('does not emit a successful preference change after a failed legacy write', async () => {
    mockInvoke.mockRejectedValue(new Error('offline'));
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const dispatch = vi.spyOn(window, 'dispatchEvent');
    await settingsClient.setPreference('permission_mode', 'read_only', 'permissions');
    expect(
      dispatch.mock.calls.filter(([event]) => event.type === 'sage:setting-changed'),
    ).toHaveLength(0);
  });
});
