import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { read } = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: { getPreferenceStrict: read, setPreferenceStrict: vi.fn() },
}));

import { displayModeStore } from '../../../features/chat/displayMode/displayModeStore';
import { __resetGlobalDisplayModeForTests } from '../../../features/chat/displayMode/globalDisplayModePreference';
import { I18nProvider } from '../../../shared/lib/i18n';
import { DisplayModeSwitch } from '../DisplayModeSwitch';

const SESSION_ID = 'session-1';

function renderSwitch() {
  return render(
    <I18nProvider>
      <DisplayModeSwitch sessionId={SESSION_ID} />
    </I18nProvider>,
  );
}

describe('DisplayModeSwitch', () => {
  beforeEach(() => {
    read.mockReset();
    read.mockResolvedValue('trace');
    __resetGlobalDisplayModeForTests();
    displayModeStore.clearAll();
    sessionStorage.clear();
  });

  it('renders collapsed and opens the menu on click', () => {
    renderSwitch();
    const button = screen.getByTestId('display-mode-button');

    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('display-mode-menu')).not.toBeInTheDocument();

    fireEvent.click(button);

    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('display-mode-menu')).toBeInTheDocument();
  });

  it('closes the menu and applies the picked session mode', () => {
    renderSwitch();
    fireEvent.click(screen.getByTestId('display-mode-button'));

    fireEvent.click(screen.getByTestId('display-mode-detail'));

    expect(screen.queryByTestId('display-mode-menu')).not.toBeInTheDocument();
    expect(displayModeStore.getSession(SESSION_ID)).toBe('detail');

    fireEvent.click(screen.getByTestId('display-mode-button'));
    expect(screen.getByTestId('display-mode-detail')).toHaveAttribute('aria-checked', 'true');
  });

  it('clears the session override so the global preference takes effect', async () => {
    read.mockResolvedValue('result');
    renderSwitch();

    fireEvent.click(screen.getByTestId('display-mode-button'));
    await waitFor(() =>
      expect(screen.getByTestId('display-mode-result')).toHaveAttribute('aria-checked', 'true'),
    );

    fireEvent.click(screen.getByTestId('display-mode-detail'));
    expect(displayModeStore.getSession(SESSION_ID)).toBe('detail');

    fireEvent.click(screen.getByTestId('display-mode-button'));
    expect(screen.getByTestId('display-mode-detail')).toHaveAttribute('aria-checked', 'true');

    fireEvent.click(screen.getByTestId('display-mode-follow-global'));

    expect(screen.queryByTestId('display-mode-menu')).not.toBeInTheDocument();
    expect(displayModeStore.getSession(SESSION_ID)).toBeNull();

    fireEvent.click(screen.getByTestId('display-mode-button'));
    expect(screen.getByTestId('display-mode-result')).toHaveAttribute('aria-checked', 'true');
  });
});
