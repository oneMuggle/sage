/**
 * lastRunState — 启动时间线/异常退出判定（纯函数 + 文件 IO）。
 *
 * 契约：
 * - createRunState 生成 running 状态；
 * - advanceStage 不可变追加阶段（毫秒相对 startedAt）；
 * - markEnded 写 clean/异常退出；
 * - classifyPrevious 区分上次 clean / unclean / 无记录；
 * - computeCrashStreak 连续异常退出计数（clean 归零）。
 */
import { describe, expect, it } from 'vitest';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import {
  advanceStage,
  classifyPrevious,
  computeCrashStreak,
  createRunState,
  markEnded,
  readLastRun,
  writeLastRun,
  type LastRunState,
} from '../lastRunState';

function makeState(): LastRunState {
  return createRunState({
    bootId: 'boot-1',
    appVersion: '0.4.9',
    electron: '21.4.4',
    safeModeLevel: 0,
    nowIso: '2026-11-08T10:00:00Z',
    nowMs: 1000,
  });
}

describe('createRunState', () => {
  it('creates a running state with initial stage', () => {
    const s = makeState();
    expect(s.schema).toBe(1);
    expect(s.bootId).toBe('boot-1');
    expect(s.endReason).toBeNull();
    expect(s.endedAt).toBeNull();
    expect(s.stage).toBe('process_start');
    expect(s.stages).toEqual([['process_start', 0]]);
  });
});

describe('advanceStage', () => {
  it('appends a relative stage immutably', () => {
    const s = makeState();
    const next = advanceStage(s, 'app_ready', 1812);
    expect(next).not.toBe(s);
    expect(s.stages).toHaveLength(1);
    expect(next.stage).toBe('app_ready');
    expect(next.stages).toEqual([
      ['process_start', 0],
      ['app_ready', 812],
    ]);
  });
});

describe('markEnded', () => {
  it('marks clean exit', () => {
    const s = markEnded(makeState(), 'clean', 'quit', '2026-11-08T10:05:00Z');
    expect(s.endReason).toBe('quit');
    expect(s.endedAt).toBe('2026-11-08T10:05:00Z');
    expect(classifyPrevious(s)).toBe('clean');
  });

  it('marks unclean exit', () => {
    const s = markEnded(makeState(), 'unclean', 'render-process-gone', '2026-11-08T10:01:00Z');
    expect(classifyPrevious(s)).toBe('unclean');
  });
});

describe('classifyPrevious', () => {
  it('returns none for missing state', () => {
    expect(classifyPrevious(null)).toBe('none');
  });

  it('returns unclean for still-running state (external kill)', () => {
    expect(classifyPrevious(makeState())).toBe('unclean');
  });
});

describe('computeCrashStreak', () => {
  it('increments on unclean', () => {
    expect(computeCrashStreak('unclean', 0)).toBe(1);
    expect(computeCrashStreak('unclean', 1)).toBe(2);
  });

  it('resets on clean', () => {
    expect(computeCrashStreak('clean', 3)).toBe(0);
  });

  it('keeps streak on none', () => {
    expect(computeCrashStreak('none', 2)).toBe(2);
  });
});

describe('file roundtrip', () => {
  it('writes and reads state', () => {
    const dir = mkdtempSync(join(tmpdir(), 'sage-lastrun-'));
    const file = join(dir, 'diagnostics', 'last-run.json');
    try {
      const s = advanceStage(makeState(), 'first_paint', 2000);
      writeLastRun(file, s);
      const raw = JSON.parse(readFileSync(file, 'utf-8'));
      expect(raw.stage).toBe('first_paint');
      const loaded = readLastRun(file);
      expect(loaded?.bootId).toBe('boot-1');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('returns null for invalid JSON', () => {
    const dir = mkdtempSync(join(tmpdir(), 'sage-lastrun-'));
    const file = join(dir, 'last-run.json');
    try {
      writeLastRun(file, makeState());
      writeFileSync(file, '{broken', 'utf-8');
      expect(readLastRun(file)).toBeNull();
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('returns null for corrupt stages (fail-open, must not crash main)', () => {
    const dir = mkdtempSync(join(tmpdir(), 'sage-lastrun-'));
    const file = join(dir, 'last-run.json');
    try {
      writeFileSync(
        file,
        JSON.stringify({ schema: 1, bootId: 'b', startedAt: '2026-11-08T10:00:00Z', stages: null }),
        'utf-8',
      );
      expect(readLastRun(file)).toBeNull();
      writeFileSync(
        file,
        JSON.stringify({
          schema: 1,
          bootId: 'b',
          startedAt: '2026-11-08T10:00:00Z',
          stages: [1, 2],
        }),
        'utf-8',
      );
      expect(readLastRun(file)).toBeNull();
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
