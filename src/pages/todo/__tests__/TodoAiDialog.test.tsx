import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ brief: vi.fn(), weekly: vi.fn() }));

vi.mock('../../../shared/api/todoClient', () => ({
  todoClient: { dailyBrief: mocks.brief, weeklyReview: mocks.weekly },
}));

import { TodoAiDialog } from '../TodoAiDialog';

beforeEach(() => {
  mocks.brief.mockReset();
  mocks.weekly.mockReset();
});

describe('TodoAiDialog', () => {
  it('loads the daily brief when opened in brief mode', async () => {
    mocks.brief.mockResolvedValue({ content: '• 处理逾期项' });

    render(<TodoAiDialog isOpen mode="brief" onClose={vi.fn()} />);

    expect(await screen.findByTestId('todo-ai-content')).toHaveTextContent('处理逾期项');
    expect(mocks.brief).toHaveBeenCalledTimes(1);
    expect(mocks.weekly).not.toHaveBeenCalled();
  });

  it('loads the weekly review in weekly mode', async () => {
    mocks.weekly.mockResolvedValue({ content: '## 完成情况' });

    render(<TodoAiDialog isOpen mode="weekly" onClose={vi.fn()} />);

    expect(await screen.findByTestId('todo-ai-content')).toHaveTextContent('完成情况');
    expect(mocks.weekly).toHaveBeenCalledTimes(1);
  });

  it('shows an error when generation fails', async () => {
    mocks.brief.mockRejectedValue(new Error('LLM 未配置'));

    render(<TodoAiDialog isOpen mode="brief" onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId('todo-ai-error').textContent).toContain('LLM 未配置');
    });
  });
});
