// electron/__tests__/logTimezone.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

let tmpDir: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'sage-logtz-test-'));
  vi.resetModules();
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  vi.resetModules();
});

vi.mock('electron', () => ({
  app: {
    // Force packaged path so getLogTimezonePath() uses app.getPath('userData')
    // (which the mock returns as tmpDir). Without this, the production code
    // takes the dev branch (process.cwd()/data/) where the directory doesn't
    // exist in CI → ENOENT failures.
    isPackaged: true,
    getPath: () => tmpDir,
  },
}));

async function importLogTimezone() {
  return import('../logTimezone');
}

describe('logTimezone', () => {
  it('readLogTimezone returns local when file does not exist', async () => {
    const { readLogTimezone } = await importLogTimezone();
    // 默认值已从 'UTC' 切换到 'local' (跟随系统本地时区, 失败回退到北京时间)
    expect(readLogTimezone()).toBe('local');
  });

  it('readLogTimezone returns stored value', async () => {
    const { readLogTimezone } = await importLogTimezone();
    // With isPackaged=true (mock), getLogTimezonePath() uses
    // app.getPath('userData') → tmpDir. So file lives at
    // ${tmpDir}/sage-log-timezone.json.
    const filePath = join(tmpDir, 'sage-log-timezone.json');
    try {
      writeFileSync(filePath, JSON.stringify({ logTimezone: 'Asia/Shanghai' }), 'utf-8');
      expect(readLogTimezone()).toBe('Asia/Shanghai');
    } finally {
      rmSync(filePath, { force: true });
    }
  });

  it('readLogTimezone returns local for malformed JSON', async () => {
    const { readLogTimezone } = await importLogTimezone();
    const filePath = join(tmpDir, 'sage-log-timezone.json');
    try {
      writeFileSync(filePath, 'not json', 'utf-8');
      expect(readLogTimezone()).toBe('local');
    } finally {
      rmSync(filePath, { force: true });
    }
  });

  it('readLogTimezone returns local when field is empty string', async () => {
    const { readLogTimezone } = await importLogTimezone();
    const filePath = join(tmpDir, 'sage-log-timezone.json');
    try {
      writeFileSync(filePath, JSON.stringify({ logTimezone: '' }), 'utf-8');
      expect(readLogTimezone()).toBe('local');
    } finally {
      rmSync(filePath, { force: true });
    }
  });

  it('writeLogTimezone writes valid JSON and readLogTimezone reads it back', async () => {
    const { writeLogTimezone, readLogTimezone } = await importLogTimezone();
    const filePath = join(tmpDir, 'sage-log-timezone.json');
    try {
      const result = writeLogTimezone('Europe/London');
      expect(result).toBe(true);
      expect(readLogTimezone()).toBe('Europe/London');
    } finally {
      rmSync(filePath, { force: true });
    }
  });
});
