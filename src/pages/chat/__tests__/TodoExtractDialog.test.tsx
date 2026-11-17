import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  extract: vi.fn(),
  batchCreate: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock('../../../shared/api/todoClient', () => ({
  todoClient: {
    extractFromSession: mocks.extract,
    batchCreate: mocks.batchCreate,
  },
}));

vi.mock('sonner', () => ({
  toast: { success: mocks.toastSuccess, error: mocks.toastError },
}));

import { TodoExtractDialog } from '../TodoExtractDialog';

beforeEach(() => {
  mocks.extract.mockReset();
  mocks.batchCreate.mockReset();
  mocks.toastSuccess.mockReset();
  mocks.toastError.mockReset();
});

describe('TodoExtractDialog', () => {
  it('renders candidates and creates selected todos with source link', async () => {
    mocks.extract.mockResolvedValue({
      candidates: [
        { title: '交报告', due_at: null, priority: 'high', tags: ['工作'] },
        { title: '约张老师', due_at: null, priority: null, tags: [] },
      ],
    });
    mocks.batchCreate.mockResolvedValue([{ id: 1 }, { id: 2 }]);
    const onClose = vi.fn();

    render(<TodoExtractDialog isOpen sessionId="s1" onClose={onClose} />);

    expect(await screen.findByDisplayValue('交报告')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('todo-extract-confirm'));

    await waitFor(() => expect(mocks.batchCreate).toHaveBeenCalledTimes(1));
    const items = mocks.batchCreate.mock.calls[0][0];
    expect(items).toHaveLength(2);
    expect(items[0]).toMatchObject({
      title: '交报告',
      priority: 'high',
      tags: ['工作'],
      source_type: 'chat',
      source_ref: 's1',
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(mocks.toastSuccess).toHaveBeenCalled();
  });

  it('shows the error message when extraction fails', async () => {
    mocks.extract.mockRejectedValue(new Error('LLM 未配置'));

    render(<TodoExtractDialog isOpen sessionId="s1" onClose={vi.fn()} />);

    const error = await screen.findByTestId('todo-extract-error');
    expect(error.textContent).toContain('LLM 未配置');
  });

  it('skips unchecked candidates', async () => {
    mocks.extract.mockResolvedValue({
      candidates: [
        { title: '保留', due_at: null, priority: null, tags: [] },
        { title: '不要', due_at: null, priority: null, tags: [] },
      ],
    });
    mocks.batchCreate.mockResolvedValue([{ id: 1 }]);

    render(<TodoExtractDialog isOpen sessionId="s1" onClose={vi.fn()} />);

    expect(await screen.findByDisplayValue('保留')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('选择 不要'));
    fireEvent.click(screen.getByTestId('todo-extract-confirm'));

    await waitFor(() => expect(mocks.batchCreate).toHaveBeenCalledTimes(1));
    expect(mocks.batchCreate.mock.calls[0][0]).toHaveLength(1);
    expect(mocks.batchCreate.mock.calls[0][0][0].title).toBe('保留');
  });
});
