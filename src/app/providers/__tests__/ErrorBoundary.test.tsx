import { describe, expect, it } from 'vitest';

import {
  formatErrorBoundaryJson,
  formatErrorBoundarySummary,
} from '../ErrorBoundary';

describe('ErrorBoundary audit helpers', () => {
  it('formats error boundary summary', () => {
    expect(formatErrorBoundarySummary(null, false)).toBe(
      'caught=false · message=none · customFallback=false',
    );
    expect(formatErrorBoundarySummary(new Error('Boom'), true)).toBe(
      'caught=true · message=Boom · customFallback=true',
    );
  });

  it('exports error boundary JSON snapshot', () => {
    expect(JSON.parse(formatErrorBoundaryJson(new Error('Crash'), false))).toEqual({
      caught: true,
      message: 'Crash',
      hasCustomFallback: false,
    });
  });
});

