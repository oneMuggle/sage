// electron/update/__tests__/featureFlag.test.ts
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';

// Mock electron module so `import { app } from 'electron'` works under vitest
// (vitest does not have a real electron runtime). app.isPackaged is read at
// call time, so we expose it as a mutable handle the tests can flip.
vi.mock('electron', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const electronMock: any = {
    app: { isPackaged: false },
  };
  return electronMock;
});

describe('featureFlag', () => {
  beforeEach(() => {
    vi.resetModules();
    delete process.env.SAGE_EXPERIMENTAL_PROVIDERS;
  });

  afterEach(() => {
    delete process.env.SAGE_EXPERIMENTAL_PROVIDERS;
  });

  it('default (env unset) is ON (Phase 3 T3.4: feature flag 全开)', async () => {
    const m = await import('../../../electron/update/featureFlag');
    expect(m.ENABLE_UPDATE_PROVIDERS_UI()).toBe(true);
  });

  it('EXPERIMENTAL env=0 forces UI off (escape hatch)', async () => {
    process.env.SAGE_EXPERIMENTAL_PROVIDERS = '0';
    const m = await import('../../../electron/update/featureFlag');
    expect(m.ENABLE_UPDATE_PROVIDERS_UI()).toBe(false);
  });

  it('EXPERIMENTAL env=1 keeps UI on (explicit)', async () => {
    process.env.SAGE_EXPERIMENTAL_PROVIDERS = '1';
    const m = await import('../../../electron/update/featureFlag');
    expect(m.ENABLE_UPDATE_PROVIDERS_UI()).toBe(true);
  });

  it('BUILTIN_GENERIC_CONFIG points to updates.sage.app', async () => {
    const m = await import('../../../electron/update/featureFlag');
    expect(m.BUILTIN_GENERIC_CONFIG.config.manifestUrl).toContain('updates.sage.app');
  });
});