// src/components/DesktopOnlyTooltip.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../hooks/usePlatform');

describe('DesktopOnlyTooltip', () => {
  afterEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it('renders children normally in electron mode', async () => {
    vi.mocked(await import('../hooks/usePlatform')).usePlatform.mockReturnValue({
      isElectron: true,
      invoke: vi.fn(),
      on: vi.fn(),
      authHeaders: {},
    });
    const { DesktopOnlyTooltip } = await import('./DesktopOnlyTooltip');

    render(
      <DesktopOnlyTooltip featureName="Test Feature">
        <button>Click me</button>
      </DesktopOnlyTooltip>,
    );
    expect(screen.getByText('Click me')).not.toBeDisabled();
  });

  it('disables children in web mode', async () => {
    vi.mocked(await import('../hooks/usePlatform')).usePlatform.mockReturnValue({
      isElectron: false,
      invoke: vi.fn(),
      on: vi.fn(),
      authHeaders: {},
    });
    const { DesktopOnlyTooltip } = await import('./DesktopOnlyTooltip');

    render(
      <DesktopOnlyTooltip featureName="Test Feature">
        <button>Click me</button>
      </DesktopOnlyTooltip>,
    );
    const wrapper = screen.getByText('Click me').parentElement;
    expect(wrapper).toHaveStyle({ opacity: 0.5, pointerEvents: 'none' });
  });
});
