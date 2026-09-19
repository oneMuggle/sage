import { describe, expect, it } from 'vitest';

import { parseCookieHeader } from '../credentialCookieParser';

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
    expect(parseCookieHeader('token=%2Bsecret')).toEqual([
      { name: 'token', value: '%2Bsecret' },
    ]);
  });
});
