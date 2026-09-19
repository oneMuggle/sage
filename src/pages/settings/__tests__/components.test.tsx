// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AdvancedSection, ApplyModeBadge } from '../components';

describe('settings shared components', () => {
  it('renders the Chinese apply-mode label', () => {
    render(<ApplyModeBadge mode="next-run" />);
    expect(screen.getByText('保存后：下次 Run')).toBeInTheDocument();
  });

  it('keeps advanced content collapsed by default', () => {
    render(
      <AdvancedSection title="高级设置">
        <div>advanced controls</div>
      </AdvancedSection>,
    );

    expect(screen.getByText('advanced controls')).not.toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /高级设置/ }));
    expect(screen.getByText('advanced controls')).toBeVisible();
  });
});
