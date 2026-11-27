import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
  confirm: vi.fn(),
  dismiss: vi.fn(),
}));

vi.mock('../../../shared/api/worklogClient', () => ({
  worklogClient: {
    list: mocks.list,
    create: mocks.create,
    update: mocks.update,
    delete: mocks.delete,
    confirm: mocks.confirm,
    dismiss: mocks.dismiss,
  },
}));

import { TodoWorklogPanel } from '../TodoWorklogPanel';

interface LogLike {
  id: number;
  content: string;
  kind: 'progress' | 'done' | 'blocker' | 'next';
  status: 'pending' | 'confirmed' | 'dismissed';
  source_type: 'chat' | 'manual' | 'agent';
  created_at: string;
  updated_at: string;
}

function makeLog(overrides: Partial<LogLike> & Pick<LogLike, 'id' | 'content'>): LogLike {
  return {
    kind: 'progress',
    status: 'confirmed',
    source_type: 'manual',
    created_at: '2026-11-27T14:32:05.123456',
    updated_at: '2026-11-27T14:32:05.123456',
    ...overrides,
  };
}

const pendingLogs: LogLike[] = [
  makeLog({ id: 11, content: '从对话抽取的候选', status: 'pending', source_type: 'chat' }),
];

const confirmedLogs: LogLike[] = [
  makeLog({ id: 21, content: '完成 P2 后端', kind: 'done', created_at: '2026-11-27T14:32:05' }),
  makeLog({ id: 22, content: '写方案文档', created_at: '2026-11-26T09:05:00' }),
];

function listResponse(items: LogLike[], limit: number) {
  return { items, total: items.length, limit, offset: 0 };
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset();
  mocks.list.mockImplementation((params?: { status?: string }) =>
    Promise.resolve(
      params?.status === 'pending'
        ? listResponse(pendingLogs, 50)
        : listResponse(confirmedLogs, 200),
    ),
  );
});

describe('TodoWorklogPanel', () => {
  it('renders the inbox and the confirmed stream grouped by day', async () => {
    render(<TodoWorklogPanel />);

    expect(await screen.findByTestId('worklog-inbox')).toBeTruthy();
    expect(screen.getByTestId('worklog-inbox-item-11').textContent).toContain('从对话抽取的候选');
    expect(screen.getByTestId('worklog-item-21').textContent).toContain('完成 P2 后端');

    const day2711 = screen.getByTestId('worklog-day-2026-11-27');
    const day2611 = screen.getByTestId('worklog-day-2026-11-26');
    expect(day2711.textContent).toContain('11 月 27 日 周五');
    expect(day2611.textContent).toContain('11 月 26 日 周四');
    expect(day2711.contains(screen.getByTestId('worklog-item-21'))).toBe(true);
    expect(day2611.contains(screen.getByTestId('worklog-item-22'))).toBe(true);
  });

  it('confirms and dismisses inbox candidates', async () => {
    mocks.confirm.mockResolvedValue(makeLog({ id: 11, content: 'x', status: 'confirmed' }));
    mocks.dismiss.mockResolvedValue(makeLog({ id: 11, content: 'x', status: 'dismissed' }));
    render(<TodoWorklogPanel />);

    fireEvent.click(await screen.findByTestId('worklog-confirm-11'));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith(11));

    fireEvent.click(screen.getByTestId('worklog-dismiss-11'));
    await waitFor(() => expect(mocks.dismiss).toHaveBeenCalledWith(11));
  });

  it('creates and immediately confirms a manual entry', async () => {
    mocks.create.mockResolvedValue(makeLog({ id: 33, content: '手记一条' }));
    mocks.confirm.mockResolvedValue(makeLog({ id: 33, content: '手记一条' }));
    render(<TodoWorklogPanel />);
    await screen.findByTestId('worklog-draft');

    fireEvent.change(screen.getByTestId('worklog-draft'), { target: { value: '手记一条' } });
    fireEvent.click(screen.getByTestId('worklog-kind-blocker'));
    fireEvent.click(screen.getByTestId('worklog-add'));

    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith(33));
    expect(mocks.create).toHaveBeenCalledWith({ content: '手记一条', kind: 'blocker' });
    await waitFor(() =>
      expect((screen.getByTestId('worklog-draft') as HTMLTextAreaElement).value).toBe(''),
    );
  });

  it('edits and deletes a confirmed entry', async () => {
    mocks.update.mockResolvedValue(makeLog({ id: 21, content: '完成 P2 前后端' }));
    mocks.delete.mockResolvedValue(undefined);
    render(<TodoWorklogPanel />);

    fireEvent.click(await screen.findByTestId('worklog-edit-21'));
    const input = screen.getByTestId('worklog-edit-input-21') as HTMLInputElement;
    expect(input.value).toBe('完成 P2 后端');
    fireEvent.change(input, { target: { value: '完成 P2 前后端' } });
    fireEvent.click(screen.getByTestId('worklog-edit-save-21'));
    await waitFor(() =>
      expect(mocks.update).toHaveBeenCalledWith(21, { content: '完成 P2 前后端' }),
    );
    await waitFor(() => expect(screen.queryByTestId('worklog-edit-input-21')).toBeNull());

    fireEvent.click(screen.getByTestId('worklog-delete-21'));
    await waitFor(() => expect(mocks.delete).toHaveBeenCalledWith(21));
  });

  it('surfaces a load error', async () => {
    mocks.list.mockRejectedValue(new Error('后端未就绪'));
    render(<TodoWorklogPanel />);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('后端未就绪');
  });
});
