import { describe, expect, it } from 'vitest';

import {
  formatArenaEntityBarrelJson,
  formatArenaEntityBarrelSummary,
} from '../index';

describe('arena entity barrel audit helpers', () => {
  it('formats arena entity barrel summary', () => {
    expect(formatArenaEntityBarrelSummary()).toBe(
      'module=entities/arena · base=/api/v1/arena · reExports=api',
    );
  });

  it('exports arena entity barrel JSON snapshot', () => {
    expect(JSON.parse(formatArenaEntityBarrelJson())).toEqual({
      module: 'entities/arena',
      base: '/api/v1/arena',
      reExports: ['api'],
    });
  });
});

