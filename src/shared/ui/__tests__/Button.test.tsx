import { describe, expect, it } from 'vitest';

import {
  formatButtonVariantJson,
  formatButtonVariantSummary,
} from '../Button';

describe('Button audit diagnostics', () => {
  it('formats button variant and size summary', () => {
    expect(formatButtonVariantSummary()).toBe('variant=primary · size=md · disabled=false');
    expect(formatButtonVariantSummary('danger', 'sm', true)).toBe(
      'variant=danger · size=sm · disabled=true',
    );
  });

  it('serializes button variant audit JSON', () => {
    const parsed = JSON.parse(formatButtonVariantJson('secondary', 'lg', false));
    expect(parsed).toEqual({
      variant: 'secondary',
      size: 'lg',
      disabled: false,
    });
  });
});
