import { describe, expect, it } from 'vitest';

import {
  formatReviewStoreJson,
  formatReviewStoreSummary,
  useReviewStore,
} from '../review-store';

describe('wiki review-store audit helpers', () => {
  it('tracks review items and formats summary', () => {
    useReviewStore.getState().reset();
    useReviewStore.getState().addItem({
      id: 'rev-1',
      type: 'contradiction',
      title: 'Auth mismatch',
      description: 'desc',
      affectedPages: ['a.md'],
      resolved: false,
      actions: [],
    });
    const state = useReviewStore.getState();
    expect(formatReviewStoreSummary(state.items, state.isLoading, state.error)).toBe(
      'status=idle · reviews=1 · unresolved=1',
    );
  });

  it('serializes review store audit JSON', () => {
    expect(JSON.parse(formatReviewStoreJson([], false, 'timeout'))).toEqual({
      reviewCount: 0,
      unresolvedCount: 0,
      isLoading: false,
      error: 'timeout',
    });
  });
});
