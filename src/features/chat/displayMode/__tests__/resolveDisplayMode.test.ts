import { describe, it, expect } from 'vitest';

import { resolveDisplayMode, getDisplayContract, type DisplayMode } from '../resolveDisplayMode';

describe('resolveDisplayMode', () => {
  it('returns message override when present', () => {
    expect(
      resolveDisplayMode({
        messageOverride: 'result',
        sessionOverride: 'detail',
        globalDefault: 'trace',
      }),
    ).toBe('result');
  });

  it('falls back to session override when message is null', () => {
    expect(
      resolveDisplayMode({
        messageOverride: null,
        sessionOverride: 'detail',
        globalDefault: 'trace',
      }),
    ).toBe('detail');
  });

  it('falls back to global default when session and message are null', () => {
    expect(
      resolveDisplayMode({
        messageOverride: null,
        sessionOverride: null,
        globalDefault: 'detail',
      }),
    ).toBe('detail');
  });

  it('falls back to trace when all overrides are null', () => {
    expect(
      resolveDisplayMode({
        messageOverride: null,
        sessionOverride: null,
        globalDefault: null,
      }),
    ).toBe('trace');
  });

  it('falls back to trace on invalid value', () => {
    expect(
      resolveDisplayMode({
        messageOverride: 'invalid' as DisplayMode,
        sessionOverride: null,
        globalDefault: null,
      }),
    ).toBe('trace');
  });
});

describe('getDisplayContract', () => {
  it('detail mode: show thinking, auto-expand while streaming', () => {
    const contract = getDisplayContract('detail');
    expect(contract.showThinkingPanel).toBe(true);
    expect(contract.thinkingDefaultExpanded).toBe(true);
    expect(contract.autoExpandWhileStreaming).toBe(true);
    expect(contract.toolGroupThreshold).toBe(3);
    expect(contract.toolGroupDefaultExpanded).toBe(true);
  });

  it('trace mode: show thinking, default collapsed', () => {
    const contract = getDisplayContract('trace');
    expect(contract.showThinkingPanel).toBe(true);
    expect(contract.thinkingDefaultExpanded).toBe(false);
    expect(contract.autoExpandWhileStreaming).toBe(false);
    expect(contract.toolGroupThreshold).toBe(3);
  });

  it('result mode: hide thinking, group all tools', () => {
    const contract = getDisplayContract('result');
    expect(contract.showThinkingPanel).toBe(false);
    expect(contract.toolGroupThreshold).toBe(1);
    expect(contract.toolGroupDefaultExpanded).toBe(false);
  });
});
