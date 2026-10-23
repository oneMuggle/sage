import { describe, expect, it } from 'vitest';

import {
  formatWorkspaceBindingJson,
  formatWorkspaceBindingSummary,
} from '../workspaceContext';

describe('workspaceContext audit diagnostics', () => {
  it('formats workspace binding summary for mounted and unmounted states', () => {
    expect(formatWorkspaceBindingSummary(null)).toBe(
      'provider=unmounted · status=idle · bound=false',
    );
    expect(
      formatWorkspaceBindingSummary({
        sessionId: 'sess-1',
        binding: {
          workspacePath: '/repo/sage',
        },
        status: 'ready',
        error: null,
      }),
    ).toBe('provider=mounted · status=ready · bound=true');
  });

  it('serializes workspace binding audit JSON', () => {
    const parsed = JSON.parse(
      formatWorkspaceBindingJson({
        sessionId: 'sess-2',
        binding: null,
        status: 'loading',
        error: null,
      }),
    );
    expect(parsed).toEqual({
      providerMounted: true,
      sessionId: 'sess-2',
      status: 'loading',
      bound: false,
      workspacePath: null,
      hasError: false,
    });
  });
});
