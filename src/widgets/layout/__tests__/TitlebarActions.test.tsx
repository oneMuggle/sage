import { render, fireEvent, waitFor } from '@testing-library/react';
import { useEffect } from 'react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';

import { NavHistoryProvider } from '../../../app/providers/NavHistoryProvider';
import { I18nProvider } from '../../../shared/lib/i18n';
import { TitlebarActions } from '../TitlebarActions';

const renderWithProvider = (initialEntries: string[] = ['/']) => {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <I18nProvider>
        <NavHistoryProvider>
          <TitlebarActions />
        </NavHistoryProvider>
      </I18nProvider>
    </MemoryRouter>,
  );
};

// Helper component that navigates on mount
function NavigateToB() {
  const navigate = useNavigate();
  useEffect(() => {
    navigate('/b');
  }, [navigate]);
  return null;
}

const renderWithNavigation = () => {
  return render(
    <MemoryRouter initialEntries={['/a']}>
      <I18nProvider>
        <NavHistoryProvider>
          <NavigateToB />
          <TitlebarActions />
        </NavHistoryProvider>
      </I18nProvider>
    </MemoryRouter>,
  );
};

describe('TitlebarActions', () => {
  it('renders back and forward buttons', () => {
    const { getByLabelText } = renderWithProvider();
    expect(getByLabelText('后退')).toBeInTheDocument();
    expect(getByLabelText('前进')).toBeInTheDocument();
  });

  it('disables back button when canBack is false', () => {
    const { getByLabelText } = renderWithProvider(['/']);
    const backBtn = getByLabelText('后退');
    expect(backBtn).toBeDisabled();
  });

  it('disables forward button when canForward is false', () => {
    const { getByLabelText } = renderWithProvider(['/']);
    const forwardBtn = getByLabelText('前进');
    expect(forwardBtn).toBeDisabled();
  });

  it('does not throw when back button clicked with history available', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { getByLabelText } = renderWithNavigation();

    await waitFor(() => {
      expect(getByLabelText('后退')).not.toBeDisabled();
    });

    const backBtn = getByLabelText('后退');
    fireEvent.click(backBtn);
    expect(consoleSpy).not.toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});
