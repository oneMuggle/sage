import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { FeedbackModal } from '../FeedbackModal';

// Mock dependencies
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

describe('FeedbackModal', () => {
  let mockOnClose: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockOnClose = vi.fn();
    vi.clearAllMocks();
    vi.spyOn(console, 'log').mockImplementation(() => {});
  });

  it('returns null when isOpen is false', () => {
    const { container } = render(
      <FeedbackModal isOpen={false} onClose={mockOnClose} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders modal content when isOpen is true', () => {
    render(<FeedbackModal isOpen={true} onClose={mockOnClose} />);

    expect(screen.getByText('发送反馈')).toBeInTheDocument();
    expect(screen.getByText('描述 *')).toBeInTheDocument();
    expect(screen.getByText('邮箱（可选）')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /提交/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /取消/i })).toBeInTheDocument();
  });

  it('renders description textarea with placeholder', () => {
    render(<FeedbackModal isOpen={true} onClose={mockOnClose} />);

    const textarea = screen.getByPlaceholderText('请描述您的问题或建议...');
    expect(textarea).toBeInTheDocument();
    expect(textarea).toHaveAttribute('required');
  });

  it('renders email input with placeholder', () => {
    render(<FeedbackModal isOpen={true} onClose={mockOnClose} />);

    const emailInput = screen.getByPlaceholderText('your@email.com');
    expect(emailInput).toBeInTheDocument();
    expect(emailInput).toHaveAttribute('type', 'email');
  });

  it('does not render screenshot preview when no screenshot provided', () => {
    render(<FeedbackModal isOpen={true} onClose={mockOnClose} />);

    expect(screen.queryByText('截图预览')).not.toBeInTheDocument();
  });

  it('renders screenshot preview when screenshot prop is provided', () => {
    const testScreenshot = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    render(<FeedbackModal isOpen={true} onClose={mockOnClose} screenshot={testScreenshot} />);

    expect(screen.getByText('截图预览')).toBeInTheDocument();
    const img = screen.getByAltText('Screenshot');
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', `data:image/png;base64,${testScreenshot}`);
  });

  it('calls onClose when cancel button is clicked', () => {
    render(<FeedbackModal isOpen={true} onClose={mockOnClose} />);

    const cancelButton = screen.getByRole('button', { name: /取消/i });
    fireEvent.click(cancelButton);

    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it('submits form and shows success message', async () => {
    render(<FeedbackModal isOpen={true} onClose={mockOnClose} />);

    const textarea = screen.getByPlaceholderText('请描述您的问题或建议...');
    const emailInput = screen.getByPlaceholderText('your@email.com');
    const submitButton = screen.getByRole('button', { name: /提交/i });

    fireEvent.change(textarea, { target: { value: 'Test feedback description' } });
    fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
    fireEvent.click(submitButton);

    // Check console.log was called with feedback data
    expect(console.log).toHaveBeenCalledWith('Feedback submitted:', {
      description: 'Test feedback description',
      email: 'test@example.com',
      screenshotLength: 0,
    });

    // Success message should appear
    await waitFor(() => {
      expect(screen.getByText('感谢您的反馈！')).toBeInTheDocument();
    });
  });

  it('resets form and calls onClose after 2 seconds on successful submit', async () => {
    vi.useFakeTimers();

    render(<FeedbackModal isOpen={true} onClose={mockOnClose} />);

    const textarea = screen.getByPlaceholderText('请描述您的问题或建议...');
    const submitButton = screen.getByRole('button', { name: /提交/i });

    fireEvent.change(textarea, { target: { value: 'Test feedback' } });
    fireEvent.click(submitButton);

    // Fast-forward time
    vi.advanceTimersByTime(2000);

    expect(mockOnClose).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });

  it('requires description field to submit', () => {
    render(<FeedbackModal isOpen={true} onClose={mockOnClose} />);

    const textarea = screen.getByPlaceholderText('请描述您的问题或建议...');
    const submitButton = screen.getByRole('button', { name: /提交/i });

    // Try to submit without description
    fireEvent.click(submitButton);

    // Form should not submit (HTML5 validation prevents it)
    expect(textarea).toBeInvalid();
  });

  it('allows optional email field', () => {
    render(<FeedbackModal isOpen={true} onClose={mockOnClose} />);

    const emailInput = screen.getByPlaceholderText('your@email.com');

    // Email is optional (no required attribute)
    expect(emailInput).not.toHaveAttribute('required');
  });

  it('handles form submission without email', async () => {
    render(<FeedbackModal isOpen={true} onClose={mockOnClose} />);

    const textarea = screen.getByPlaceholderText('请描述您的问题或建议...');
    const submitButton = screen.getByRole('button', { name: /提交/i });

    fireEvent.change(textarea, { target: { value: 'Feedback without email' } });
    fireEvent.click(submitButton);

    expect(console.log).toHaveBeenCalledWith('Feedback submitted:', {
      description: 'Feedback without email',
      email: '',
      screenshotLength: 0,
    });
  });

  it('submits form with screenshot data when provided', async () => {
    const testScreenshot = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    render(<FeedbackModal isOpen={true} onClose={mockOnClose} screenshot={testScreenshot} />);

    const textarea = screen.getByPlaceholderText('请描述您的问题或建议...');
    const submitButton = screen.getByRole('button', { name: /提交/i });

    fireEvent.change(textarea, { target: { value: 'Feedback with screenshot' } });
    fireEvent.click(submitButton);

    expect(console.log).toHaveBeenCalledWith('Feedback submitted:', {
      description: 'Feedback with screenshot',
      email: '',
      screenshotLength: testScreenshot.length,
    });
  });
});
