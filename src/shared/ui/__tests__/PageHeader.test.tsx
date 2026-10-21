import { describe, expect, it } from 'vitest';

import {
  formatPageHeaderJson,
  formatPageHeaderSummary,
} from '../PageHeader';

describe('PageHeader audit diagnostics', () => {
  it('formats page header summary', () => {
    expect(formatPageHeaderSummary('Settings', true, false)).toBe(
      'title=Settings · subtitle=true · actions=false',
    );
    expect(formatPageHeaderSummary('', false, true)).toBe(
      'title=untitled · subtitle=false · actions=true',
    );
  });

  it('serializes page header audit JSON', () => {
    const parsed = JSON.parse(formatPageHeaderJson('Skills', true, true));
    expect(parsed).toEqual({
      title: 'Skills',
      hasSubtitle: true,
      hasActions: true,
    });
  });
});
