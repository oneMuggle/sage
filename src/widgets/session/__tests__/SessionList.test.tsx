import { describe, it, expect } from 'vitest';

import { SessionList } from '../SessionList';

describe('SessionList', () => {
  it('module exports a component function', () => {
    expect(typeof SessionList).toBe('function');
  });
});
