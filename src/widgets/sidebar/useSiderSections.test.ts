import { describe, it, expect } from 'vitest';

import { useSiderSections } from './useSiderSections';

describe('useSiderSections', () => {
  it('module exports a hook function', () => {
    expect(typeof useSiderSections).toBe('function');
  });
});
