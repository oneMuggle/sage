/**
 * crashJournal — 结构化崩溃事件日志（NDJSON）。
 */
import { describe, expect, it } from 'vitest';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import { appendCrashEvent, buildCrashEvent } from '../crashJournal';

describe('buildCrashEvent', () => {
  it('captures reason/exitCode/type with iso timestamp', () => {
    const evt = buildCrashEvent(
      { reason: 'killed', exitCode: 1, type: 'renderer', rendererPid: 4321 },
      {
        bootId: 'boot-1',
        appVersion: '0.4.9',
        electron: '21.4.4',
        safeModeLevel: 0,
        windowAgeMs: 2300,
        url: 'file:///app/index.html',
        route: '/chat',
        nowIso: '2026-11-08T10:00:00Z',
      },
    );
    expect(evt.ts).toBe('2026-11-08T10:00:00Z');
    expect(evt.reason).toBe('killed');
    expect(evt.exitCode).toBe(1);
    expect(evt.type).toBe('renderer');
    expect(evt.rendererPid).toBe(4321);
    expect(evt.safeModeLevel).toBe(0);
    expect(evt.url).toContain('index.html');
  });

  it('tolerates missing details', () => {
    const evt = buildCrashEvent(
      {},
      {
        bootId: 'b',
        appVersion: 'v',
        electron: 'e',
        safeModeLevel: 0,
        nowIso: '2026-11-08T10:00:00Z',
      },
    );
    expect(evt.reason).toBe('unknown');
    expect(evt.exitCode).toBeNull();
  });
});

describe('appendCrashEvent', () => {
  it('creates parent dir and appends one NDJSON line per event', () => {
    const dir = mkdtempSync(join(tmpdir(), 'sage-journal-'));
    const file = join(dir, 'diagnostics', 'crash-journal.jsonl');
    try {
      const evt1 = buildCrashEvent(
        { reason: 'crashed' },
        {
          bootId: 'b1',
          appVersion: 'v',
          electron: 'e',
          safeModeLevel: 0,
          nowIso: '2026-11-08T10:00:00Z',
        },
      );
      const evt2 = buildCrashEvent(
        { reason: 'killed' },
        {
          bootId: 'b1',
          appVersion: 'v',
          electron: 'e',
          safeModeLevel: 0,
          nowIso: '2026-11-08T10:01:00Z',
        },
      );
      appendCrashEvent(file, evt1);
      appendCrashEvent(file, evt2);
      const lines = readFileSync(file, 'utf-8').trim().split('\n');
      expect(lines).toHaveLength(2);
      expect(JSON.parse(lines[0]).reason).toBe('crashed');
      expect(JSON.parse(lines[1]).reason).toBe('killed');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
