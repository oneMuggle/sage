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
    isPackaged: false,
    getPath: () => tmpDir,
  },
}));

async function importLogTimezone() {
  return import('../logTimezone');
}

describe('logTimezone', () => {
  it('readLogTimezone returns UTC when file does not exist', async () => {
    const { readLogTimezone } = await importLogTimezone();
    expect(readLogTimezone()).toBe('UTC');
  });

  it('readLogTimezone returns stored value', async () => {
    const { readLogTimezone } = await importLogTimezone();
    // In dev mode (isPackaged=false), path is cwd()/data/sage-log-timezone.json
    const dataDir = join(process.cwd(), 'data');
    const filePath = join(dataDir, 'sage-log-timezone.json');
    try {
      writeFileSync(filePath, JSON.stringify({ logTimezone: 'Asia/Shanghai' }), 'utf-8');
      expect(readLogTimezone()).toBe('Asia/Shanghai');
    } finally {
      rmSync(filePath, { force: true });
    }
  });

  it('readLogTimezone returns UTC for malformed JSON', async () => {
    const { readLogTimezone } = await importLogTimezone();
    const dataDir = join(process.cwd(), 'data');
    const filePath = join(dataDir, 'sage-log-timezone.json');
    try {
      writeFileSync(filePath, 'not json', 'utf-8');
      expect(readLogTimezone()).toBe('UTC');
    } finally {
      rmSync(filePath, { force: true });
    }
  });

  it('readLogTimezone returns UTC when field is empty string', async () => {
    const { readLogTimezone } = await importLogTimezone();
    const dataDir = join(process.cwd(), 'data');
    const filePath = join(dataDir, 'sage-log-timezone.json');
    try {
      writeFileSync(filePath, JSON.stringify({ logTimezone: '' }), 'utf-8');
      expect(readLogTimezone()).toBe('UTC');
    } finally {
      rmSync(filePath, { force: true });
    }
  });

  it('writeLogTimezone writes valid JSON and readLogTimezone reads it back', async () => {
    const { writeLogTimezone, readLogTimezone } = await importLogTimezone();
    const dataDir = join(process.cwd(), 'data');
    const filePath = join(dataDir, 'sage-log-timezone.json');
    try {
      const result = writeLogTimezone('Europe/London');
      expect(result).toBe(true);
      expect(readLogTimezone()).toBe('Europe/London');
    } finally {
      rmSync(filePath, { force: true });
    }
  });
});
