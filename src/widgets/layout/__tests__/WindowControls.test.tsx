import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import type { WindowControlsBridge } from '../../../shared/api/windowControlsClient';
import { I18nProvider } from '../../../shared/lib/i18n';
import { WindowControls } from '../WindowControls';

function renderWithI18n(ui: React.ReactElement) {
  return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
}

describe('WindowControls', () => {
  let mockBridge: WindowControlsBridge;

  beforeEach(() => {
    mockBridge = {
      minimize: vi.fn().mockResolvedValue(undefined),
      toggleMaximize: vi.fn().mockResolvedValue(undefined),
      close: vi.fn().mockResolvedValue(undefined),
      capturePage: vi.fn().mockResolvedValue('base64data'),
      isMaximized: vi.fn().mockResolvedValue(false),
    };
  });

  it('renders 3 buttons with aria-labels', () => {
    renderWithI18n(<WindowControls bridge={mockBridge} />);

    expect(screen.getByRole('button', { name: /最小化/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /最大化/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /关闭/i })).toBeInTheDocument();
  });

  it('calls bridge.minimize when minimize button clicked', async () => {
    renderWithI18n(<WindowControls bridge={mockBridge} />);

    const minimizeBtn = screen.getByRole('button', { name: /最小化/i });
    fireEvent.click(minimizeBtn);

    expect(mockBridge.minimize).toHaveBeenCalledTimes(1);
  });

  it('calls bridge.toggleMaximize when maximize button clicked', async () => {
    renderWithI18n(<WindowControls bridge={mockBridge} />);

    const maximizeBtn = screen.getByRole('button', { name: /最大化/i });
    fireEvent.click(maximizeBtn);

    expect(mockBridge.toggleMaximize).toHaveBeenCalledTimes(1);
  });

  it('calls bridge.close when close button clicked', async () => {
    renderWithI18n(<WindowControls bridge={mockBridge} />);

    const closeBtn = screen.getByRole('button', { name: /关闭/i });
    fireEvent.click(closeBtn);

    expect(mockBridge.close).toHaveBeenCalledTimes(1);
  });

  it('handles IPC errors gracefully without throwing to UI', async () => {
    const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockBridge.minimize = vi.fn().mockRejectedValue(new Error('IPC failed'));

    renderWithI18n(<WindowControls bridge={mockBridge} />);

    const minimizeBtn = screen.getByRole('button', { name: /最小化/i });
    fireEvent.click(minimizeBtn);

    // Wait for async operations
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Should log warning but not throw
    expect(consoleWarnSpy).toHaveBeenCalled();
    expect(minimizeBtn).toBeEnabled();

    consoleWarnSpy.mockRestore();
  });

  it('uses windowControls singleton when bridge prop not provided', () => {
    renderWithI18n(<WindowControls />);

    // Should still render without crashing
    expect(screen.getByRole('button', { name: /最小化/i })).toBeInTheDocument();
  });
});
