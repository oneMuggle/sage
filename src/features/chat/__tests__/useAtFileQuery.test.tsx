// src/features/chat/__tests__/useAtFileQuery.test.tsx
import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useAtFileQuery } from '../useAtFileQuery';

describe('useAtFileQuery', () => {
  it('returns null when no @ in input', () => {
    const { result } = renderHook(() => useAtFileQuery('hello world', 5));
    expect(result.current).toEqual({
      query: null,
      startIdx: 0,
      endIdx: 0,
    });
  });

  it('extracts @query when cursor is after @', () => {
    const { result } = renderHook(() => useAtFileQuery('hello @foo', 10));
    expect(result.current).toEqual({
      query: 'foo',
      startIdx: 6,
      endIdx: 10,
    });
  });

  it('returns null when cursor is before @', () => {
    const { result } = renderHook(() => useAtFileQuery('hello @foo', 3));
    expect(result.current).toEqual({
      query: null,
      startIdx: 0,
      endIdx: 0,
    });
  });

  it('returns empty query when cursor is right after @', () => {
    const { result } = renderHook(() => useAtFileQuery('hello @', 7));
    expect(result.current).toEqual({
      query: '',
      startIdx: 6,
      endIdx: 7,
    });
  });

  it('handles @ at start of input', () => {
    const { result } = renderHook(() => useAtFileQuery('@foo', 4));
    expect(result.current).toEqual({
      query: 'foo',
      startIdx: 0,
      endIdx: 4,
    });
  });

  it('returns null when @ is not preceded by whitespace or start', () => {
    const { result } = renderHook(() => useAtFileQuery('email@foo', 9));
    expect(result.current).toEqual({
      query: null,
      startIdx: 0,
      endIdx: 0,
    });
  });

  it('handles multiple @ symbols', () => {
    const { result } = renderHook(() => useAtFileQuery('@foo @bar', 9));
    expect(result.current).toEqual({
      query: 'bar',
      startIdx: 5,
      endIdx: 9,
    });
  });
});
