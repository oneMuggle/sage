import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { FeedbackButton } from '../FeedbackButton';
import * as windowControlsClient from '../../../shared/api/windowControlsClient';

// Mock dependencies
vi.mock('../../../shared/api/windowControlsClient', () => ({
  windowControls: {
    capturePage: vi.fn(),
  },
}));

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'feedback.button': '反馈',
        'feedback.title': '发送反馈',
        'feedback.screenshot': '截图预览',
        'feedback.description': '描述',
        'feedback.description_placeholder': '请描述您的问题或建议...',
        'feedback.email': '邮箱（可选）',
        'feedback.email_placeholder': 'your@email.com',
        'feedback.submit': '提交',
        'feedback.success': '感谢您的反馈！',
        'common.cancel': '取消',
      };
      return translations[key] || key;
    },
  }),
}));

describe('FeedbackButton', () => {
  const mockCapturePage = windowControlsClient.windowControls.capturePage as ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('renders feedback button with correct label', () => {
    render(<FeedbackButton />);

    const button = screen.getByRole('button', { name: /反馈/i });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute('title', '反馈');
  });

  it('opens modal when clicked', async () => {
    mockCapturePage.mockResolvedValue('base64screenshot');

    render(<FeedbackButton />);

    const button = screen.getByRole('button', { name: /反馈/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(mockCapturePage).toHaveBeenCalled();
    });

    // Modal should be visible
    expect(screen.getByText('发送反馈')).toBeInTheDocument();
  });

  it('shows error in console when capturePage fails', async () => {
    mockCapturePage.mockRejectedValue(new Error('Capture failed'));

    render(<FeedbackButton />);

    const button = screen.getByRole('button', { name: /反馈/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(mockCapturePage).toHaveBeenCalled();
    });

    expect(console.error).toHaveBeenCalledWith(
      'Failed to capture screenshot:',
      expect.any(Error)
    );

    // Modal should still open even if capture fails
    expect(screen.getByText('发送反馈')).toBeInTheDocument();
  });

  it('closes modal when cancel button is clicked', async () => {
    mockCapturePage.mockResolvedValue('base64screenshot');

    render(<FeedbackButton />);

    const button = screen.getByRole('button', { name: /反馈/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText('发送反馈')).toBeInTheDocument();
    });

    const cancelButton = screen.getByRole('button', { name: /取消/i });
    fireEvent.click(cancelButton);

    await waitFor(() => {
      expect(screen.queryByText('发送反馈')).not.toBeInTheDocument();
    });
  });
});
