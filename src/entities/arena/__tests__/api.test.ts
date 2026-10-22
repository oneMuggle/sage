import { describe, expect, it } from 'vitest';

import {
  formatArenaAccountJson,
  formatArenaAccountSummary,
} from '../api';

describe('arena api audit helpers', () => {
  it('formats arena account summary', () => {
    expect(
      formatArenaAccountSummary({
        id: 'acc-1',
        state: 'available',
        failure_count: 2,
      }),
    ).toBe('id=acc-1 · state=available · failures=2');
    expect(
      formatArenaAccountSummary({
        id: '   ',
        state: 'degraded',
        failure_count: -1,
      }),
    ).toBe('id=unknown · state=degraded · failures=0');
  });

  it('exports arena account JSON snapshot', () => {
    expect(
      JSON.parse(
        formatArenaAccountJson({
          id: 'acc-9',
          state: 'reserved',
          failure_count: 0,
        }),
      ),
    ).toEqual({
      id: 'acc-9',
      state: 'reserved',
      failures: 0,
    });
  });
});

