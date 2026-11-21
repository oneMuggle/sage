import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DesignProgressStrip } from '../DesignProgressStrip';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

describe('DesignProgressStrip', () => {
  it('maps known stages to i18n keys', () => {
    render(<DesignProgressStrip stage="linting" />);
    expect(screen.getByText('design.stage.linting')).toBeTruthy();
  });

  it('falls back to the raw stage for unknown values', () => {
    render(<DesignProgressStrip stage="mystery" />);
    expect(screen.getByText('mystery')).toBeTruthy();
  });
});
