/**
 * rescueDialogs — 原生恢复对话框按钮映射 + 启动器路径解析。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockShowMessageBox = vi.fn();
const mockOpenPath = vi.fn();
const mockGetPath = vi.fn(() => '/mock/userData');

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: mockGetPath,
    getVersion: vi.fn(() => '0.4.9'),
  },
  dialog: { showMessageBox: mockShowMessageBox },
  shell: { openPath: mockOpenPath },
}));

vi.mock('../logger', () => ({
  logger: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockShowMessageBox.mockReset();
  mockShowMessageBox.mockResolvedValue({ response: 0 });
  mockOpenPath.mockReset();
  mockOpenPath.mockResolvedValue('');
});

describe('showCrashRecoveryDialog', () => {
  it('maps response 0 to safe-mode', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showCrashRecoveryDialog } = await import('../rescueDialogs');
    const choice = await showCrashRecoveryDialog({
      crashCount: 2,
      reason: 'render-process-gone:killed',
      safeModeLevel: 1,
    });
    expect(choice).toBe('safe-mode');
  });

  it('maps response 1 to repair-tool', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 1 });
    const { showCrashRecoveryDialog } = await import('../rescueDialogs');
    expect(await showCrashRecoveryDialog({ crashCount: 1, reason: 'x', safeModeLevel: 0 })).toBe(
      'repair-tool',
    );
  });

  it('maps response 2 to report', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 2 });
    const { showCrashRecoveryDialog } = await import('../rescueDialogs');
    expect(await showCrashRecoveryDialog({ crashCount: 1, reason: 'x', safeModeLevel: 0 })).toBe(
      'report',
    );
  });

  it('maps response 3 to quit', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 3 });
    const { showCrashRecoveryDialog } = await import('../rescueDialogs');
    expect(await showCrashRecoveryDialog({ crashCount: 1, reason: 'x', safeModeLevel: 0 })).toBe(
      'quit',
    );
  });

  it('falls back to quit when dialog throws', async () => {
    mockShowMessageBox.mockRejectedValue(new Error('dialog unavailable'));
    const { showCrashRecoveryDialog } = await import('../rescueDialogs');
    expect(await showCrashRecoveryDialog({ crashCount: 1, reason: 'x', safeModeLevel: 0 })).toBe(
      'quit',
    );
  });
});

describe('resolveRescueLauncherPath', () => {
  it('finds resources/SageDoctor.cmd in dev checkout', async () => {
    const { resolveRescueLauncherPath } = await import('../rescueDialogs');
    const path = resolveRescueLauncherPath();
    expect(path).toMatch(/resources[\\/]SageDoctor\.cmd$/);
  });
});

describe('openRescueTool', () => {
  it('shows a terminal hint on non-Windows dev instead of opening .cmd', async () => {
    const { openRescueTool } = await import('../rescueDialogs');
    const ok = await openRescueTool();
    if (process.platform === 'win32') {
      expect(ok).toBe(true);
      expect(mockOpenPath).toHaveBeenCalled();
    } else {
      expect(ok).toBe(false);
      expect(mockShowMessageBox).toHaveBeenCalled();
      expect(mockOpenPath).not.toHaveBeenCalled();
    }
  });
});
