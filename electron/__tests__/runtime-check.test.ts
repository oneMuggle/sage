/**
 * runtime-check — Windows 版本判断与运行时检测门控.
 *
 * 重点验证 isLegacyWindows() 的 NT major 判断逻辑:
 * - Win7 SP1 (6.1) → legacy
 * - Win10 / Server 2019 (10.0) → 非 legacy
 * - 非 Win32 平台 → false
 */
import { describe, expect, it, vi, afterEach } from 'vitest';

describe('isLegacyWindows', () => {
  const originalPlatform = process.platform;
  const originalGetSystemVersion = process.getSystemVersion;

  afterEach(() => {
    vi.resetModules();
    Object.defineProperty(process, 'platform', { value: originalPlatform });
    (process as { getSystemVersion?: typeof process.getSystemVersion }).getSystemVersion =
      originalGetSystemVersion;
  });

  function mockWindows(version: string): void {
    Object.defineProperty(process, 'platform', { value: 'win32', configurable: true });
    (process as { getSystemVersion: () => string }).getSystemVersion = () => version;
  }

  function mockNonWindows(platform: NodeJS.Platform): void {
    Object.defineProperty(process, 'platform', { value: platform, configurable: true });
  }

  it('returns true for Win7 SP1 (6.1.7601)', async () => {
    mockWindows('6.1.7601');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(true);
  });

  it('returns true for Win8 (6.2.9200)', async () => {
    mockWindows('6.2.9200');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(true);
  });

  it('returns true for Win8.1 (6.3.9600)', async () => {
    mockWindows('6.3.9600');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(true);
  });

  it('returns false for Win10 (10.0.19041)', async () => {
    mockWindows('10.0.19041');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false for Win11 (10.0.22000)', async () => {
    mockWindows('10.0.22000');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false for Server 2019 (10.0.17763)', async () => {
    mockWindows('10.0.17763');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false for Server 2022 (10.0.20348)', async () => {
    mockWindows('10.0.20348');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false on Linux', async () => {
    mockNonWindows('linux');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false on macOS', async () => {
    mockNonWindows('darwin');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false if getSystemVersion throws', async () => {
    Object.defineProperty(process, 'platform', { value: 'win32', configurable: true });
    (process as { getSystemVersion: () => string }).getSystemVersion = () => {
      throw new Error('not supported');
    };
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });
});

describe('runRuntimeChecks platform gating', () => {
  const originalPlatform = process.platform;

  afterEach(() => {
    vi.resetModules();
    Object.defineProperty(process, 'platform', { value: originalPlatform });
  });

  it('returns single ok result on non-win32 platforms', async () => {
    Object.defineProperty(process, 'platform', { value: 'linux', configurable: true });
    vi.resetModules();
    const { runRuntimeChecks } = await import('../runtime-check');
    const results = await runRuntimeChecks();
    expect(results).toHaveLength(1);
    expect(results[0].name).toBe('platform');
    expect(results[0].severity).toBe('ok');
  });
});

// ── isLegacyWindows: 平台门控 (2026-11 从 main 同步) ──────────────────────

describe('isLegacyWindows', () => {
  const originalPlatform = process.platform;
  const originalGetSystemVersion = process.getSystemVersion;

  afterEach(() => {
    vi.resetModules();
    Object.defineProperty(process, 'platform', { value: originalPlatform });
    (process as { getSystemVersion?: typeof process.getSystemVersion }).getSystemVersion =
      originalGetSystemVersion;
  });

  function mockWindows(version: string): void {
    Object.defineProperty(process, 'platform', { value: 'win32', configurable: true });
    (process as { getSystemVersion: () => string }).getSystemVersion = () => version;
  }

  function mockNonWindows(platform: NodeJS.Platform): void {
    Object.defineProperty(process, 'platform', { value: platform, configurable: true });
  }

  it('returns true for Win7 SP1 (6.1.7601)', async () => {
    mockWindows('6.1.7601');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(true);
  });

  it('returns true for Win8 (6.2.9200)', async () => {
    mockWindows('6.2.9200');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(true);
  });

  it('returns true for Win8.1 (6.3.9600)', async () => {
    mockWindows('6.3.9600');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(true);
  });

  it('returns false for Win10 (10.0.19041)', async () => {
    mockWindows('10.0.19041');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false for Win11 (10.0.22000)', async () => {
    mockWindows('10.0.22000');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false for Server 2019 (10.0.17763)', async () => {
    mockWindows('10.0.17763');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false for Server 2022 (10.0.20348)', async () => {
    mockWindows('10.0.20348');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false on Linux', async () => {
    mockNonWindows('linux');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false on macOS', async () => {
    mockNonWindows('darwin');
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });

  it('returns false if getSystemVersion throws', async () => {
    Object.defineProperty(process, 'platform', { value: 'win32', configurable: true });
    (process as { getSystemVersion: () => string }).getSystemVersion = () => {
      throw new Error('not supported');
    };
    vi.resetModules();
    const { isLegacyWindows } = await import('../runtime-check');
    expect(isLegacyWindows()).toBe(false);
  });
});
