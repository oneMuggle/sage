import { describe, it, expect } from 'vitest';

import { SortableSessionList } from '../SortableSessionList';

describe('SortableSessionList', () => {
  it('module exports a component function', () => {
    expect(typeof SortableSessionList).toBe('function');
  });
});
