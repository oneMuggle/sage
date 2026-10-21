import { describe, expect, it } from 'vitest';

import {
  formatBadgeVariantJson,
  formatBadgeVariantSummary,
} from '../Badge';

describe('Badge audit diagnostics', () => {
  it('formats badge variant summary', () => {
    expect(formatBadgeVariantSummary()).toBe('variant=default · pill=true');
    expect(formatBadgeVariantSummary('destructive')).toBe('variant=destructive · pill=true');
  });

  it('serializes badge variant audit JSON', () => {
    const parsed = JSON.parse(formatBadgeVariantJson('outline'));
    expect(parsed).toEqual({
      variant: 'outline',
      pill: true,
    });
  });
});
