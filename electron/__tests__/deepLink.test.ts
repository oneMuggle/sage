/**
 * E-1 (round5 批次 E): sage:// 深链解析纯函数测试
 */
import { describe, expect, it } from 'vitest';

import { extractSageUrlFromArgv, parseSageDeepLink } from '../deepLink';

describe('parseSageDeepLink', () => {
  it('parses sage://chat?session=<id>', () => {
    expect(parseSageDeepLink('sage://chat?session=abc-123')).toEqual({
      sessionId: 'abc-123',
    });
  });

  it('rejects non-sage protocols', () => {
    expect(parseSageDeepLink('https://chat?session=x')).toBeNull();
    expect(parseSageDeepLink('')).toBeNull();
  });

  it('rejects unknown hosts', () => {
    expect(parseSageDeepLink('sage://settings?foo=1')).toBeNull();
  });

  it('rejects missing or malformed session ids', () => {
    expect(parseSageDeepLink('sage://chat')).toBeNull();
    expect(parseSageDeepLink('sage://chat?session=')).toBeNull();
    expect(parseSageDeepLink('sage://chat?session=bad charset!')).toBeNull();
  });

  it('accepts uuid session ids', () => {
    expect(
      parseSageDeepLink('sage://chat?session=a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d'),
    ).toEqual({ sessionId: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d' });
  });
});

describe('extractSageUrlFromArgv', () => {
  it('finds sage url among argv entries', () => {
    expect(
      extractSageUrlFromArgv(['--flag', 'sage://chat?session=abc', 'other']),
    ).toBe('sage://chat?session=abc');
  });

  it('returns null when no sage url present', () => {
    expect(extractSageUrlFromArgv(['--flag', 'other'])).toBeNull();
    expect(extractSageUrlFromArgv([])).toBeNull();
  });
});
