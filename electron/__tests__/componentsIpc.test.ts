import { EventEmitter } from 'events';
import { PassThrough } from 'stream';
import { describe, expect, it, vi } from 'vitest';

import type { ResolveOpts } from '../backendLauncher';
import {
  isValidComponentId,
  parseComponentEvents,
  runComponentCli,
  validatePackagePath,
} from '../componentsIpc';

function makeOpts(): ResolveOpts {
  return {
    env: {},
    resourcesPath: '/mock/resources',
    platform: 'win32',
    isPackaged: false,
    sageDbPath: '/mock/sage.db',
    sageUserDataDir: '/mock/userData',
    port: 8765,
    existsSyncFn: () => true,
  };
}

describe('parseComponentEvents', () => {
  it('parses progress and result JSON lines, ignoring noise', () => {
    const events = parseComponentEvents(
      [
        'warning: not json',
        '{"event":"progress","phase":"extract","done":1,"total":2}',
        '{"event":"result","ok":true,"installed":[]}',
      ].join('\n'),
    );
    expect(events).toHaveLength(2);
    expect(events[0].event).toBe('progress');
    expect(events[1].event).toBe('result');
  });
});

describe('component path/id validation', () => {
  it('accepts only absolute .sagepkg paths', () => {
    expect(validatePackagePath('/tmp/model.sagepkg')).toBe(true);
    expect(validatePackagePath('C:\\Sage\\model.SAGEPKG')).toBe(true);
    expect(validatePackagePath('model.sagepkg')).toBe(false);
    expect(validatePackagePath('/tmp/model.zip')).toBe(false);
  });

  it('rejects traversal in component ids', () => {
    expect(isValidComponentId('embedding-bge-small-zh')).toBe(true);
    expect(isValidComponentId('../sage')).toBe(false);
    expect(isValidComponentId('Demo')).toBe(false);
  });
});

describe('runComponentCli', () => {
  it('streams progress and returns the final result event', async () => {
    const child = new EventEmitter() as EventEmitter & {
      stdout: PassThrough;
      stderr: PassThrough;
      kill: ReturnType<typeof vi.fn>;
    };
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    child.kill = vi.fn();
    const spawnFn = vi.fn(() => child);
    const progress = vi.fn();

    const pending = runComponentCli(['list', '--json'], {
      resolveOpts: makeOpts,
      onEvent: progress,
      timeoutMs: 5_000,
      spawnFn: spawnFn as never,
    });

    child.stdout.write(
      '{"event":"progress","phase":"extract","message":"a","done":1,"total":2}\n',
    );
    child.stdout.write('{"event":"result","ok":true,"installed":[],"discovered":[]}\n');
    child.stdout.end();
    child.emit('close', 0);

    const { result } = await pending;
    expect(result?.ok).toBe(true);
    expect(progress).toHaveBeenCalledTimes(1);
    expect(spawnFn).toHaveBeenCalledOnce();
  });

  it('returns a structured error when the CLI emits no result', async () => {
    const child = new EventEmitter() as EventEmitter & {
      stdout: PassThrough;
      stderr: PassThrough;
      kill: ReturnType<typeof vi.fn>;
    };
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    child.kill = vi.fn();

    const pending = runComponentCli(['list', '--json'], {
      resolveOpts: makeOpts,
      timeoutMs: 5_000,
      spawnFn: (() => child) as never,
    });
    child.stderr.write('boom');
    child.stdout.end();
    child.stderr.end();
    child.emit('close', 1);

    const { result } = await pending;
    expect(result?.ok).toBe(false);
    expect(result?.code).toBe('cli_failed');
    expect(result?.error).toContain('boom');
  });
});
