import { describe, expect, it } from 'vitest';

import { DEFAULT_PET_CONFIG } from '../pet/config';
import { shouldShowDesktop, shouldShowInApp } from '../pet/display';

function configWith(displayMode: 'desktop' | 'in-app' | 'both' | 'off') {
  return { ...DEFAULT_PET_CONFIG, enabled: true, displayMode };
}

describe('pet display modes', () => {
  it('shows the desktop overlay only for desktop/both', () => {
    expect(shouldShowDesktop(configWith('desktop'))).toBe(true);
    expect(shouldShowDesktop(configWith('both'))).toBe(true);
    expect(shouldShowDesktop(configWith('in-app'))).toBe(false);
    expect(shouldShowDesktop(configWith('off'))).toBe(false);
  });

  it('shows the in-app dock only for in-app/both', () => {
    expect(shouldShowInApp(configWith('desktop'))).toBe(false);
    expect(shouldShowInApp(configWith('both'))).toBe(true);
    expect(shouldShowInApp(configWith('in-app'))).toBe(true);
    expect(shouldShowInApp(configWith('off'))).toBe(false);
  });

  it('hides everything when disabled', () => {
    const disabled = { ...configWith('both'), enabled: false };
    expect(shouldShowDesktop(disabled)).toBe(false);
    expect(shouldShowInApp(disabled)).toBe(false);
  });
});
