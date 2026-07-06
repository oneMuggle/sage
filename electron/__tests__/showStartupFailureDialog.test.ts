// electron/__tests__/showStartupFailureDialog.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, existsSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const mockShowMessageBox = vi.fn();
const mockShellOpenPath = vi.fn();
const mockQuit = vi.fn();

vi.mock('electron', () => ({
  dialog: { showMessageBox: mockShowMessageBox },
  shell: { openPath: mockShellOpenPath },
  app: { quit: mockQuit, getPath: vi.fn(() => '/mock/userData') },
}));

let tmpDir: string;
let originalEnv: Record<string, string | undefined>;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'sage-failure-dialog-test-'));
  originalEnv = { SAGE_LOG_DIR: process.env.SAGE_LOG_DIR };
  process.env.SAGE_LOG_DIR = tmpDir;
  vi.resetModules();
  vi.clearAllMocks();
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  if (originalEnv.SAGE_LOG_DIR === undefined) delete process.env.SAGE_LOG_DIR;
  else process.env.SAGE_LOG_DIR = originalEnv.SAGE_LOG_DIR;
});

describe('showStartupFailureDialog', () => {
  it('logs error before showing dialog', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showStartupFailureDialog } = await import('../showStartupFailureDialog');
    await showStartupFailureDialog({ reason: 'backend timeout' });

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
    expect(existsSync(file)).toBe(true);
    const lines = readFileSync(file, 'utf-8').trim().split('\n').filter(Boolean);
    const startupLine = lines.find((l) => l.includes('startup failed'));
    expect(startupLine).toBeDefined();
  });

  it('returns "open-logs" when first button chosen', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showStartupFailureDialog } = await import('../showStartupFailureDialog');
    const result = await showStartupFailureDialog({ reason: 'fail' });
    expect(result).toBe('open-logs');
    expect(mockShellOpenPath).toHaveBeenCalled();
  });

  it('returns "quit" and calls app.quit when third button chosen', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 2 });
    const { showStartupFailureDialog } = await import('../showStartupFailureDialog');
    const result = await showStartupFailureDialog({ reason: 'fail' });
    expect(result).toBe('quit');
    expect(mockQuit).toHaveBeenCalled();
  });

  it('appends stderrTail lines to the dialog detail when provided', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showStartupFailureDialog } = await import('../showStartupFailureDialog');
    const stderr = [
      'Traceback (most recent call last):',
      '  File "<string>", line 1, in <module>',
      "ModuleNotFoundError: No module named 'fastapi'",
    ];
    await showStartupFailureDialog({ reason: 'backend timeout', stderrTail: stderr });

    expect(mockShowMessageBox).toHaveBeenCalledTimes(1);
    const opts = mockShowMessageBox.mock.calls[0][0];
    expect(opts.detail).toContain('最近后端输出');
    expect(opts.detail).toContain("ModuleNotFoundError: No module named 'fastapi'");
    // All 3 lines should appear in order
    for (const line of stderr) {
      expect(opts.detail).toContain(line);
    }
  });

  it('omits stderr section when stderrTail is empty or missing', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showStartupFailureDialog } = await import('../showStartupFailureDialog');
    await showStartupFailureDialog({ reason: 'no stderr' });

    const opts = mockShowMessageBox.mock.calls[0][0];
    expect(opts.detail).not.toContain('最近后端输出');
  });
});