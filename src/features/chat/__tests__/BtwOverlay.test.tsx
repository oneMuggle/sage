import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useBtwState } from '../../../entities/chat/btwState';
import { BtwOverlay } from '../BtwOverlay';

// Mock i18n hook
vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'chat.btw.title': '补充问题',
        'chat.btw.question': '问题',
        'chat.btw.loading': '思考中...',
        'chat.btw.close': '关闭',
      };
      return translations[key] || key;
    },
  }),
}));

// Mock useBtwCommand hook
const mockOpen = vi.fn();
const mockClose = vi.fn();
vi.mock('../useBtwCommand', () => ({
  useBtwCommand: () => ({
    open: mockOpen,
    close: mockClose,
  }),
}));

describe('BtwOverlay', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset BtwState to initial
    useBtwState.getState().close();
  });

  it('should not render when isOpen is false', () => {
    render(<BtwOverlay />);
    expect(screen.queryByTestId('btw-overlay')).not.toBeInTheDocument();
  });

  it('should render question when isOpen is true', () => {
    useBtwState.getState().open('What is React?');
    render(<BtwOverlay />);

    expect(screen.getByTestId('btw-overlay')).toBeInTheDocument();
    expect(screen.getByText('What is React?')).toBeInTheDocument();
  });

  it('should render answer when available', () => {
    useBtwState.getState().open('Question');
    useBtwState.getState().appendDelta('This is the answer');
    render(<BtwOverlay />);

    expect(screen.getByText('This is the answer')).toBeInTheDocument();
  });

  it('should show loading indicator when isLoading is true', () => {
    useBtwState.getState().open('Question');
    // State is loading after open
    render(<BtwOverlay />);

    expect(screen.getByTestId('btw-loading')).toBeInTheDocument();
  });

  it('should hide loading indicator when isLoading is false', () => {
    useBtwState.getState().open('Question');
    useBtwState.getState().appendDelta('Answer');
    // State is not loading after appendDelta
    render(<BtwOverlay />);

    expect(screen.queryByTestId('btw-loading')).not.toBeInTheDocument();
  });

  it('should call close when close button is clicked', () => {
    useBtwState.getState().open('Question');
    render(<BtwOverlay />);

    const closeButton = screen.getByTestId('btw-close');
    fireEvent.click(closeButton);

    expect(mockClose).toHaveBeenCalledTimes(1);
  });

  it('should call close when Escape key is pressed', () => {
    useBtwState.getState().open('Question');
    render(<BtwOverlay />);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(mockClose).toHaveBeenCalledTimes(1);
  });

  it('should display title from i18n', () => {
    useBtwState.getState().open('Question');
    render(<BtwOverlay />);

    expect(screen.getByText('补充问题')).toBeInTheDocument();
  });
});
