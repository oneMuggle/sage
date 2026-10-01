/**
 * P1-1: 记忆「暂停新增」与「彻底清除」必须分离（对标 Claude Pause / Reset）。
 *
 * 此前只有 autoMemory 开关（关闭 = 停止新增），没有任何清除入口 ——
 * 用户事实上无法清空记忆库。关掉开关不会删除已有内容，这一点必须在 UI
 * 上说清楚，否则用户会误以为「关了就没了」。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getMemoriesMock = vi.fn();
const deleteMemoryMock = vi.fn();

vi.mock('../../../shared/api', () => ({
  memoryApi: {
    getMemories: (...args: unknown[]) => getMemoriesMock(...args),
    deleteMemory: (...args: unknown[]) => deleteMemoryMock(...args),
  },
}));

vi.mock('../../../shared/api/desktopInvoke', () => ({ invoke: vi.fn(async () => null) }));
// AutoCheckpointCard 走 settingsClient 偏好读写
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getPreference: vi.fn(async () => null),
    setPreference: vi.fn(async () => undefined),
  },
}));
vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: { autoMemory: true, confirmDelete: true },
    updateSettings: vi.fn(),
  }),
}));
// 与本次改动无关的重组件，隔离出去
vi.mock('../ContextTurnLimitSelect', () => ({ ContextTurnLimitSelect: () => null }));
vi.mock('../components', () => ({
  SettingRow: ({ label, desc, children }: { label: string; desc?: string; children: React.ReactNode }) => (
    <div>
      <span>{label}</span>
      {desc ? <span>{desc}</span> : null}
      {children}
    </div>
  ),
  Toggle: () => <input type="checkbox" readOnly />,
}));
vi.mock('sonner', () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

import { MemoryKnowledgeTab } from '../MemoryKnowledgeTab';

function page(items: Array<{ id: string }>, total = items.length) {
  return { items, page: 1, total, page_size: items.length, layer: 'all' as const, source_breakdown: {} };
}

async function clickClearAll() {
  fireEvent.click(await screen.findByTestId('clear-all-memories-button'));
  await screen.findByTestId('clear-all-confirm');
}

describe('P1-1 清除全部记忆', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getMemoriesMock.mockResolvedValue(page([]));
    deleteMemoryMock.mockResolvedValue(undefined);
  });

  it('开关文案澄清：关闭只停止新增，不删除已有', () => {
    render(<MemoryKnowledgeTab />);
    expect(screen.getByText(/关闭只停止新增，已记住的内容仍保留/)).toBeInTheDocument();
  });

  it('统计后展示条数，未输入确认短语时禁止执行', async () => {
    getMemoriesMock.mockResolvedValue(page([{ id: 'a' }, { id: 'b' }], 2));
    render(<MemoryKnowledgeTab />);
    await clickClearAll();

    expect(screen.getByTestId('clear-all-confirm').textContent).toContain('2');
    expect(screen.getByTestId('clear-all-confirm-yes')).toBeDisabled();

    fireEvent.change(screen.getByTestId('clear-all-confirm-input'), { target: { value: '随便写' } });
    expect(screen.getByTestId('clear-all-confirm-yes')).toBeDisabled();
    expect(deleteMemoryMock).not.toHaveBeenCalled();
  });

  it('输入正确短语后逐条删除并报告成功', async () => {
    getMemoriesMock
      .mockResolvedValueOnce(page([{ id: 'a' }, { id: 'b' }], 2))
      .mockResolvedValueOnce(page([{ id: 'a' }, { id: 'b' }], 2))
      .mockResolvedValue(page([]));
    render(<MemoryKnowledgeTab />);
    await clickClearAll();

    fireEvent.change(screen.getByTestId('clear-all-confirm-input'), {
      target: { value: '清除全部记忆' },
    });
    fireEvent.click(screen.getByTestId('clear-all-confirm-yes'));

    await waitFor(() => expect(deleteMemoryMock).toHaveBeenCalledTimes(2), { timeout: 5000 });
    expect(deleteMemoryMock).toHaveBeenCalledWith('a');
    expect(deleteMemoryMock).toHaveBeenCalledWith('b');
    await waitFor(() => expect(screen.getByTestId('clear-all-done')).toBeTruthy(), { timeout: 5000 });
    expect(toast.success).toHaveBeenCalledWith('已清除 2 条记忆');
  }, 20000);

  it('取消则不删除任何内容', async () => {
    getMemoriesMock.mockResolvedValue(page([{ id: 'a' }], 1));
    render(<MemoryKnowledgeTab />);
    await clickClearAll();

    fireEvent.click(screen.getByTestId('clear-all-confirm-no'));

    await waitFor(() => expect(screen.queryByTestId('clear-all-confirm')).toBeNull());
    expect(deleteMemoryMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('clear-all-memories-button')).toBeTruthy();
  });

  it('单条失败不中断整体，并如实报告失败数（不谎称全部清除）', async () => {
    getMemoriesMock
      .mockResolvedValueOnce(page([{ id: 'a' }, { id: 'b' }], 2))
      .mockResolvedValueOnce(page([{ id: 'a' }, { id: 'b' }], 2))
      .mockResolvedValue(page([]));
    deleteMemoryMock.mockImplementation(async (id: string) => {
      if (id === 'b') throw new Error('locked');
    });
    render(<MemoryKnowledgeTab />);
    await clickClearAll();

    fireEvent.change(screen.getByTestId('clear-all-confirm-input'), {
      target: { value: '清除全部记忆' },
    });
    fireEvent.click(screen.getByTestId('clear-all-confirm-yes'));

    await waitFor(() => expect(deleteMemoryMock).toHaveBeenCalledTimes(2), { timeout: 5000 });
    await waitFor(() => expect(screen.getByTestId('clear-all-done')).toBeTruthy(), { timeout: 5000 });
    expect(screen.getByTestId('clear-all-done').textContent).toContain('1 条失败');
    expect(toast.warning).toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  }, 20000);

  it('统计失败时回到初始态并报错，不进入确认步骤', async () => {
    getMemoriesMock.mockRejectedValueOnce(new Error('db down'));
    render(<MemoryKnowledgeTab />);

    fireEvent.click(await screen.findByTestId('clear-all-memories-button'));

    await waitFor(() => expect(toast.error).toHaveBeenCalled(), { timeout: 5000 });
    expect(screen.queryByTestId('clear-all-confirm')).toBeNull();
    expect(screen.getByTestId('clear-all-memories-button')).toBeTruthy();
  }, 20000);
});
