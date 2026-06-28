import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

function renderInput(props: Partial<React.ComponentProps<typeof ChatInput>> = {}) {
  return render(
    <I18nProvider>
      <ChatInput onSend={() => {}} isLoading={false} {...props} />
    </I18nProvider>,
  );
}

describe('ChatInput scheduled button', () => {
  it('renders schedule button when onSchedule is provided', () => {
    renderInput({ onSchedule: vi.fn() });
    expect(screen.getByTitle(/定时/i)).toBeTruthy();
  });

  it('clicking schedule button invokes onSchedule', () => {
    const onSchedule = vi.fn();
    renderInput({ onSchedule });
    fireEvent.click(screen.getByTitle(/定时/i));
    expect(onSchedule).toHaveBeenCalledTimes(1);
  });

  it('does not render schedule button when onSchedule is undefined', () => {
    renderInput();
    expect(screen.queryByTitle(/定时/i)).toBeNull();
  });
});
