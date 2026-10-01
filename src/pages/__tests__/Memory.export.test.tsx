import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getMemoriesMock = vi.fn();
const createObjectUrlMock = vi.fn(() => 'blob:memory-export');
const revokeObjectUrlMock = vi.fn();

vi.mock('../../shared/api', () => ({
  memoryApi: {
    getMemories: (...args: unknown[]) => getMemoriesMock(...args),
  },
}));

vi.mock('../../widgets/memory', () => ({
  MemoryBrowser: () => <div data-testid="memory-browser" />,
  NewMemoryModal: () => null,
  UserProfileCard: () => null,
  ProjectProfileCard: () => null,
}));

vi.mock('../../shared/ui/ErrorState', () => ({
  ErrorState: ({ title, message }: { title: string; message: string }) => (
    <div role="alert">
      <span>{title}</span>
      <span>{message}</span>
    </div>
  ),
}));

import { Memory } from '../Memory';

// P0-6: Memory 页读取 /memory?focus=<id> 深链参数，需在 Router 内渲染。
function renderMemory() {
  return render(
    <MemoryRouter initialEntries={['/memory']}>
      <Memory />
    </MemoryRouter>,
  );
}

function response(
  items: Array<{ id: string }>,
  page: number,
  total: number,
) {
  return {
    items,
    page,
    total,
    page_size: items.length,
    layer: 'all' as const,
    source_breakdown: { episodic: total, semantic: 0 },
  };
}

describe('Memory export pagination', () => {
  beforeEach(() => {
    getMemoriesMock.mockReset();
    createObjectUrlMock.mockClear();
    revokeObjectUrlMock.mockClear();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: createObjectUrlMock,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: revokeObjectUrlMock,
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('merges multiple pages in API order before downloading', async () => {
    getMemoriesMock
      .mockResolvedValueOnce(response([{ id: 'first' }], 1, 2))
      .mockResolvedValueOnce(response([{ id: 'second' }], 2, 2));

    renderMemory();
    await screen.findByRole('button', { name: '导出' });
    screen.getByRole('button', { name: '导出' }).click();

    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce());
    expect(getMemoriesMock).toHaveBeenNthCalledWith(1, undefined, 1, 100);
    expect(getMemoriesMock).toHaveBeenNthCalledWith(2, undefined, 2, 100);
    expect(createObjectUrlMock).toHaveBeenCalledOnce();
  });

  it('reports a page mismatch without downloading', async () => {
    getMemoriesMock.mockResolvedValue(response([{ id: 'first' }], 2, 1));

    renderMemory();
    screen.getByRole('button', { name: '导出' }).click();

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('超过当前导出上限'));
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  });

  it('rejects a response whose declared total exceeds the export cap', async () => {
    getMemoriesMock.mockResolvedValue(response([{ id: 'first' }], 1, 1001));

    renderMemory();
    screen.getByRole('button', { name: '导出' }).click();

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('超过当前导出上限'));
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  });

  it('bails out on first response when total exceeds cap, instead of looping until backend clamp', async () => {
    // Backend in production clamps page>10 → 10. Without the early total check
    // the loop issues 10 doomed requests before the page mismatch triggers.
    // Realistic clamp scenario: full first page + declared total > cap.
    const firstPage = Array.from({ length: 100 }, (_, index) => ({ id: `m-${index}` }));
    getMemoriesMock.mockResolvedValue(response(firstPage, 1, 1500));

    renderMemory();
    screen.getByRole('button', { name: '导出' }).click();

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('超过当前导出上限'));
    expect(getMemoriesMock).toHaveBeenCalledTimes(1);
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  });

  it('rejects more items than the export cap even when total is within the cap', async () => {
    const items = Array.from({ length: 1001 }, (_, index) => ({ id: `m-${index}` }));
    getMemoriesMock.mockResolvedValue(response(items, 1, 1000));

    renderMemory();
    screen.getByRole('button', { name: '导出' }).click();

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('超过当前导出上限'));
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  });

  it('reports an incomplete middle page without downloading', async () => {
    getMemoriesMock
      .mockResolvedValueOnce(response([{ id: 'first' }], 1, 3))
      .mockResolvedValueOnce(response([], 2, 3));

    renderMemory();
    screen.getByRole('button', { name: '导出' }).click();

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('分页不完整'));
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  });
});
