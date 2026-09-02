import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Mock } from 'vitest';

import * as windowControlsClient from '../../../shared/api/windowControlsClient';
import { Titlebar } from '../Titlebar';

// Mock dependencies
vi.mock('../../../shared/api/windowControlsClient', () => ({
  detectPlatform: vi.fn(),
  isElectronDesktop: vi.fn((platform) => platform !== 'web'),
}));

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

vi.mock('../TitlebarActions', () => ({
  TitlebarActions: () => <div data-testid="titlebar-actions">TitlebarActions</div>,
}));

vi.mock('../WindowControls', () => ({
  WindowControls: () => <div data-testid="window-controls">WindowControls</div>,
}));

describe('Titlebar', () => {
  const mockDetectPlatform = windowControlsClient.detectPlatform as Mock;
  const mockIsElectronDesktop = windowControlsClient.isElectronDesktop as Mock;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('renders TitlebarActions on all platforms', () => {
    mockDetectPlatform.mockReturnValue('web');
    mockIsElectronDesktop.mockReturnValue(false);

    render(<Titlebar />);

    expect(screen.getByTestId('titlebar-actions')).toBeInTheDocument();
  });

  it('renders WindowControls on Windows', () => {
    mockDetectPlatform.mockReturnValue('windows');
    mockIsElectronDesktop.mockReturnValue(true);

    render(<Titlebar />);

    expect(screen.getByTestId('window-controls')).toBeInTheDocument();
  });

  it('renders WindowControls on Linux', () => {
    mockDetectPlatform.mockReturnValue('linux');
    mockIsElectronDesktop.mockReturnValue(true);

    render(<Titlebar />);

    expect(screen.getByTestId('window-controls')).toBeInTheDocument();
  });

  it('does NOT render WindowControls on macOS (native traffic lights)', () => {
    mockDetectPlatform.mockReturnValue('macos');
    mockIsElectronDesktop.mockReturnValue(true);

    render(<Titlebar />);

    expect(screen.queryByTestId('window-controls')).not.toBeInTheDocument();
  });

  it('does NOT render WindowControls on web', () => {
    mockDetectPlatform.mockReturnValue('web');
    mockIsElectronDesktop.mockReturnValue(false);

    render(<Titlebar />);

    expect(screen.queryByTestId('window-controls')).not.toBeInTheDocument();
  });

  it('applies pt-7 class on macOS for traffic light offset', () => {
    mockDetectPlatform.mockReturnValue('macos');
    mockIsElectronDesktop.mockReturnValue(true);

    const { container } = render(<Titlebar />);

    expect(container.firstChild).toHaveClass('pt-7');
  });

  it('applies h-9 class on Windows/Linux', () => {
    mockDetectPlatform.mockReturnValue('windows');
    mockIsElectronDesktop.mockReturnValue(true);

    const { container } = render(<Titlebar />);

    expect(container.firstChild).toHaveClass('h-9');
  });

  it('applies h-10 class on web and macOS', () => {
    mockDetectPlatform.mockReturnValue('web');
    mockIsElectronDesktop.mockReturnValue(false);

    const { container } = render(<Titlebar />);

    expect(container.firstChild).toHaveClass('h-10');
  });

  // U-Brand: Windows/Linux 渲染 brand logo；macOS/web 不渲染（空间留给 traffic lights / 简洁）
  it('renders brand logo on Windows', () => {
    mockDetectPlatform.mockReturnValue('windows');
    mockIsElectronDesktop.mockReturnValue(true);

    render(<Titlebar />);

    // useI18n mock 返回 identity：t('brand.alt') === 'brand.alt'
    expect(screen.getByRole('img', { name: 'brand.alt' })).toBeInTheDocument();
  });

  it('renders brand logo on Linux', () => {
    mockDetectPlatform.mockReturnValue('linux');
    mockIsElectronDesktop.mockReturnValue(true);

    render(<Titlebar />);

    expect(screen.getByRole('img', { name: 'brand.alt' })).toBeInTheDocument();
  });

  it('does NOT render brand logo on macOS (traffic lights take precedence)', () => {
    mockDetectPlatform.mockReturnValue('macos');
    mockIsElectronDesktop.mockReturnValue(true);

    render(<Titlebar />);

    expect(screen.queryByRole('img', { name: 'brand.alt' })).not.toBeInTheDocument();
  });

  it('does NOT render brand logo on web', () => {
    mockDetectPlatform.mockReturnValue('web');
    mockIsElectronDesktop.mockReturnValue(false);

    render(<Titlebar />);

    expect(screen.queryByRole('img', { name: 'brand.alt' })).not.toBeInTheDocument();
  });
});
