/**
 * Tests for the readiness-gate error type added by Task 0 review round 1.
 *
 * This test lives next to invoke.test.ts (same module under test,
 * same mock fixture pattern). It asserts:
 *   - BackendNotReadyError is thrown with the stable `code` field
 *   - The default message is the Chinese string the renderer matches on
 *   - It is an instanceof Error so IPC marshalling behaves correctly
 */
import { describe, expect, it } from 'vitest';
import { BackendNotReadyError } from '../invoke';

describe('BackendNotReadyError', () => {
  it('exposes the stable code marker for renderer dispatch', () => {
    const err = new BackendNotReadyError();
    expect(err.code).toBe('BACKEND_NOT_READY');
    expect(err.name).toBe('BackendNotReadyError');
  });

  it('uses the Chinese default message that desktopInvoke.ts matches on', () => {
    const err = new BackendNotReadyError();
    expect(err.message).toContain('后端服务尚未就绪');
  });

  it('accepts a custom message override', () => {
    const err = new BackendNotReadyError('custom chinese override');
    expect(err.message).toBe('custom chinese override');
    expect(err.code).toBe('BACKEND_NOT_READY');
  });

  it('is an instanceof Error so IPC marshalling behaves correctly', () => {
    const err = new BackendNotReadyError();
    expect(err).toBeInstanceOf(Error);
    expect(err.stack).toBeTypeOf('string');
  });
});