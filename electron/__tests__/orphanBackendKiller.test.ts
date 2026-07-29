// electron/__tests__/orphanBackendKiller.test.ts
import { describe, it, expect } from 'vitest';
import {
  killOrphanedBackendOnPort,
  extractPidsFromNetstat,
  type KillOrphanOpts,
} from '../orphanBackendKiller';

/**
 * Build a fake `execSyncFn` that returns staged output for specific
 * commands. Unrecognized commands throw, mimicking a real failure.
 */
function makeExecSync(
  script: Record<string, string | ((cmd: string) => string)>,
): (cmd: string, _opts?: { encoding: string }) => string {
  return (cmd: string): string => {
    // Match by prefix so the exact `netstat ... | findstr ...` pipeline works.
    for (const [prefix, response] of Object.entries(script)) {
      if (cmd.startsWith(prefix)) {
        if (typeof response === 'function') return response(cmd);
        return response;
      }
    }
    // findstr exits 1 on no match — simulate for netstat queries not staged.
    if (cmd.startsWith('netstat')) {
      const err = new Error('findstr: no match');
      (err as unknown as { status: number }).status = 1;
      throw err;
    }
    // taskkill failures
    if (cmd.startsWith('taskkill')) {
      const err = new Error('taskkill: process not found');
      (err as unknown as { status: number }).status = 128;
      throw err;
    }
    throw new Error(`unexpected command: ${cmd}`);
  };
}

function makeOpts(overrides: Partial<KillOrphanOpts> = {}): KillOrphanOpts {
  return {
    port: 8765,
    platform: 'win32',
    selfPid: 99999,
    ...overrides,
  };
}

describe('extractPidsFromNetstat', () => {
  it('extracts a single PID from standard netstat output', () => {
    const out = '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    12345\r\n';
    expect(extractPidsFromNetstat(out, 99999)).toEqual(['12345']);
  });

  it('extracts multiple PIDs (IPv4 + IPv6 listeners) and dedupes', () => {
    const out = [
      '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    12345',
      '  TCP    [::]:8765       [::]:0       LISTENING    12345',
      '  TCP    127.0.0.1:8765  0.0.0.0:0    LISTENING    67890',
    ].join('\r\n');
    // 12345 appears twice but must be deduped.
    expect(extractPidsFromNetstat(out, 99999)).toEqual(['12345', '67890']);
  });

  it('filters out self PID', () => {
    const out = '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    99999\r\n';
    expect(extractPidsFromNetstat(out, 99999)).toEqual([]);
  });

  it('filters out PID 0 and PID 1', () => {
    const out = [
      '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    0',
      '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    1',
      '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    42',
    ].join('\r\n');
    expect(extractPidsFromNetstat(out, 99999)).toEqual(['42']);
  });

  it('skips non-numeric PIDs and short lines', () => {
    const out = [
      'Proto  Local Address          Foreign Address        State       PID',
      '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    NOTAPID',
      'short line',
      '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    5555',
    ].join('\r\n');
    expect(extractPidsFromNetstat(out, 99999)).toEqual(['5555']);
  });

  it('returns empty array for empty input', () => {
    expect(extractPidsFromNetstat('', 99999)).toEqual([]);
    expect(extractPidsFromNetstat('\r\n\r\n', 99999)).toEqual([]);
  });
});

describe('killOrphanedBackendOnPort', () => {
  it('returns skipped=non-windows on linux', () => {
    const result = killOrphanedBackendOnPort(makeOpts({ platform: 'linux' }));
    expect(result).toEqual({ kind: 'skipped', reason: 'non-windows' });
  });

  it('returns skipped=non-windows on darwin', () => {
    const result = killOrphanedBackendOnPort(makeOpts({ platform: 'darwin' }));
    expect(result).toEqual({ kind: 'skipped', reason: 'non-windows' });
  });

  it('returns none-found when netstat has no listeners', () => {
    const execSyncFn = makeExecSync({});
    const result = killOrphanedBackendOnPort(makeOpts({ execSyncFn }));
    expect(result).toEqual({ kind: 'none-found' });
  });

  it('kills a single orphan and returns its PID', () => {
    const killed: string[] = [];
    const execSyncFn = makeExecSync({
      netstat: '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    12345\r\n',
      taskkill: (_cmd: string) => {
        const match = _cmd.match(/\/PID\s+(\d+)/);
        if (match) killed.push(match[1]!);
        return '';
      },
    });
    const result = killOrphanedBackendOnPort(makeOpts({ execSyncFn }));
    expect(result).toEqual({ kind: 'killed', pids: ['12345'] });
    expect(killed).toEqual(['12345']);
  });

  it('kills multiple orphans and dedupes', () => {
    const killed: string[] = [];
    const execSyncFn = makeExecSync({
      netstat: [
        '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    111',
        '  TCP    [::]:8765       [::]:0       LISTENING    111',
        '  TCP    127.0.0.1:8765  0.0.0.0:0    LISTENING    222',
      ].join('\r\n'),
      taskkill: (_cmd: string) => {
        const match = _cmd.match(/\/PID\s+(\d+)/);
        if (match) killed.push(match[1]!);
        return '';
      },
    });
    const result = killOrphanedBackendOnPort(makeOpts({ execSyncFn }));
    expect(result).toEqual({ kind: 'killed', pids: ['111', '222'] });
    expect(killed).toEqual(['111', '222']);
  });

  it('does not kill self PID even if listed', () => {
    const killed: string[] = [];
    const execSyncFn = makeExecSync({
      netstat: '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    99999\r\n',
      taskkill: (_cmd: string) => {
        const match = _cmd.match(/\/PID\s+(\d+)/);
        if (match) killed.push(match[1]!);
        return '';
      },
    });
    const result = killOrphanedBackendOnPort(makeOpts({ execSyncFn, selfPid: 99999 }));
    expect(result).toEqual({ kind: 'none-found' });
    expect(killed).toEqual([]);
  });

  it('tolerates taskkill failure (race: process exited between netstat and taskkill)', () => {
    const execSyncFn = makeExecSync({
      netstat: '  TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    12345\r\n',
      // taskkill not staged → falls through to default which throws
    });
    // Must not throw; returns none-found because no kills succeeded.
    const result = killOrphanedBackendOnPort(makeOpts({ execSyncFn }));
    expect(result).toEqual({ kind: 'none-found' });
  });

  it('uses custom port in netstat command', () => {
    let receivedCmd = '';
    const execSyncFn = (cmd: string) => {
      receivedCmd = cmd;
      throw Object.assign(new Error('no match'), { status: 1 });
    };
    killOrphanedBackendOnPort(makeOpts({ port: 9999, execSyncFn }));
    expect(receivedCmd).toContain(':9999');
  });
});
