import { describe, expect, it } from 'vitest';

import { parseCookieHeader } from '../credentialCookieParser';
import { formatCookieHeaderJson, formatCookieHeaderSummary } from '../credentialCookieParser';

describe('parseCookieHeader', () => {
  it('parses document.cookie pairs and preserves equals in values', () => {
    expect(parseCookieHeader('SID=opaque; theme=light; token=a=b')).toEqual([
      { name: 'SID', value: 'opaque' },
      { name: 'theme', value: 'light' },
      { name: 'token', value: 'a=b' },
    ]);
  });

  it('rejects empty input and malformed segments', () => {
    expect(() => parseCookieHeader('')).toThrow();
    expect(() => parseCookieHeader('SID=opaque; malformed')).toThrow();
  });

  it('does not decode or print cookie values', () => {
    expect(parseCookieHeader('token=%2Bsecret')).toEqual([{ name: 'token', value: '%2Bsecret' }]);
  });

  it('formats cookie header summary and JSON without exposing secret values (Phase P111)', () => {
    const items = parseCookieHeader('SID=opaque; token=%2Bsecret');
    expect(formatCookieHeaderSummary(items)).toBe('count=2 · names=[SID,token]');
    const json = formatCookieHeaderJson(items);
    expect(json).not.toContain('opaque');
    expect(json).not.toContain('%2Bsecret');
    expect(JSON.parse(json)).toEqual({
      count: 2,
      names: ['SID', 'token'],
    });
  });
});
