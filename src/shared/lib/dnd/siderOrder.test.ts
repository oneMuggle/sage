import { describe, it, expect } from 'vitest';

import {
  readStoredSiderOrder,
  writeStoredSiderOrder,
  reconcileStoredSiderOrder,
  sortSiderItemsByStoredOrder,
  areSiderOrdersEqual,
  reorderSiderIds,
} from './siderOrder';

describe('siderOrder (pure)', () => {
  it('module exports 6 functions', () => {
    expect(typeof readStoredSiderOrder).toBe('function');
    expect(typeof writeStoredSiderOrder).toBe('function');
    expect(typeof reconcileStoredSiderOrder).toBe('function');
    expect(typeof sortSiderItemsByStoredOrder).toBe('function');
    expect(typeof areSiderOrdersEqual).toBe('function');
    expect(typeof reorderSiderIds).toBe('function');
  });
});
