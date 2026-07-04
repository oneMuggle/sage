// electron/__tests__/logger.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, readFileSync, existsSync, appendFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

let tmpDir: string;
let originalEnv: Record<string, string | undefined>;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), 'sage-logger-test-'));
  originalEnv = {
    SAGE_LOG_DIR: process.env.SAGE_LOG_DIR,
    SAGE_LOG_LEVEL: process.env.SAGE_LOG_LEVEL,
  };
  process.env.SAGE_LOG_DIR = tmpDir;
  process.env.SAGE_LOG_LEVEL = 'debug';
  vi.resetModules();
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  for (const [k, v] of Object.entries(originalEnv)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  vi.resetModules();
});

async function importLogger() {
  const mod = await import('../logger');
  return mod.logger;
}

describe('logger', () => {
  it('writes NDJSON line with required fields', async () => {
    const logger = await importLogger();
    logger.info('hello world', { foo: 'bar' });

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
    expect(existsSync(file)).toBe(true);

    const lines = readFileSync(file, 'utf-8').trim().split('\n');
    expect(lines).toHaveLength(1);
    const obj = JSON.parse(lines[0]);

    expect(obj).toMatchObject({
      level: 'info',
      source: 'main',
      msg: 'hello world',
      meta: { foo: 'bar' },
    });
    expect(obj.ts).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  });

  it('respects SAGE_LOG_LEVEL filtering', async () => {
    process.env.SAGE_LOG_LEVEL = 'warn';
    const logger = await importLogger();

    logger.debug('should-not-appear');
    logger.info('also-not');
    logger.warn('yes-warn');
    logger.error('yes-error');

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
    if (!existsSync(file)) return;

    const lines = readFileSync(file, 'utf-8').trim().split('\n').filter(Boolean);
    const levels = lines.map((l) => JSON.parse(l).level);
    expect(levels).not.toContain('debug');
    expect(levels).not.toContain('info');
    expect(levels).toContain('warn');
    expect(levels).toContain('error');
  });

  it('falls back to string when meta has circular reference', async () => {
    const logger = await importLogger();
    const circular: Record<string, unknown> = { a: 1 };
    circular.self = circular;

    logger.error('circular', circular);

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
    const lines = readFileSync(file, 'utf-8').trim().split('\n');
    const obj = JSON.parse(lines[0]);

    expect(obj.level).toBe('error');
    expect(obj.msg).toBe('circular');
    expect(typeof obj.meta.self).toBe('string');
    expect(obj.meta.self).toBe('[unserializable]');
    expect(obj.meta.a).toBe(1);
  });

  it('omits meta field when not provided', async () => {
    const logger = await importLogger();
    logger.info('no meta');

    const today = new Date().toISOString().slice(0, 10);
    const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
    const obj = JSON.parse(readFileSync(file, 'utf-8').trim());

    expect(obj.msg).toBe('no meta');
    expect(obj.meta).toBeUndefined();
  });

  it('appends to existing file (does not overwrite)', async () => {
    const logsDir = join(tmpDir, 'logs');
    mkdirSync(logsDir, { recursive: true });
    const today = new Date().toISOString().slice(0, 10);
    const file = join(logsDir, `sage-${today}.ndjson`);
    appendFileSync(file, '{"existing":true}\n', 'utf-8');

    const logger = await importLogger();
    logger.info('appended');

    const lines = readFileSync(file, 'utf-8').trim().split('\n');
    expect(lines).toHaveLength(2);
    expect(JSON.parse(lines[0])).toEqual({ existing: true });
    expect(JSON.parse(lines[1]).msg).toBe('appended');
  });
});