import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../entities/autonomous-goals/goalApi', () => ({
  listGoals: vi.fn(),
}));
vi.mock('../../../shared/api/todoClient', () => ({
  todoClient: { list: vi.fn() },
}));
vi.mock('../../../shared/api/scheduledClient', () => ({
  scheduledClient: { list: vi.fn() },
}));

import { listGoals } from '../../../entities/autonomous-goals/goalApi';
import { scheduledClient } from '../../../shared/api/scheduledClient';
import { todoClient } from '../../../shared/api/todoClient';
import { resetUnifiedTaskStore, useUnifiedTaskStore } from '../unifiedTaskStore';

const goal = { id: 'g1', name: 'g', status: 'pending' } as never;
const todo = { id: 1, title: 't', status: 'pending' } as never;
const task = { id: 's1', name: 's', last_status: 'never' } as never;

describe('unifiedTaskStore', () => {
  beforeEach(() => {
    resetUnifiedTaskStore();
    vi.resetAllMocks();
  });

  it('refresh 同时拉三源并解包两种返回形状', async () => {
    vi.mocked(listGoals).mockResolvedValue({
      items: [goal],
      total: 1,
      limit: 200,
      offset: 0,
    } as never);
    vi.mocked(todoClient.list).mockResolvedValue({
      items: [todo],
      total: 1,
      limit: 200,
      offset: 0,
    } as never);
    vi.mocked(scheduledClient.list).mockResolvedValue([task] as never);

    await useUnifiedTaskStore.getState().refresh();

    const s = useUnifiedTaskStore.getState();
    expect(s.goals).toEqual([goal]);
    expect(s.todos).toEqual([todo]);
    expect(s.scheduledTasks).toEqual([task]);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
    expect(s.lastFetchedAt).toBeTypeOf('number');
  });

  it('显式传 limit=200 与 include_completed=true（不依赖默认 limit=50）', async () => {
    vi.mocked(listGoals).mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 } as never);
    vi.mocked(todoClient.list).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
    } as never);
    vi.mocked(scheduledClient.list).mockResolvedValue([] as never);

    await useUnifiedTaskStore.getState().refresh();

    expect(listGoals).toHaveBeenCalledWith(undefined, 200, 0);
    expect(todoClient.list).toHaveBeenCalledWith({
      limit: 200,
      offset: 0,
      include_completed: true,
    });
  });

  it('单源失败不阻断其余两源（部分失败语义）', async () => {
    vi.mocked(listGoals).mockRejectedValue(new Error('goal down'));
    vi.mocked(todoClient.list).mockResolvedValue({
      items: [todo],
      total: 1,
      limit: 200,
      offset: 0,
    } as never);
    vi.mocked(scheduledClient.list).mockResolvedValue([task] as never);

    await useUnifiedTaskStore.getState().refresh();

    const s = useUnifiedTaskStore.getState();
    expect(s.goals).toEqual([]);
    expect(s.todos).toEqual([todo]);
    expect(s.scheduledTasks).toEqual([task]);
    expect(s.error).toBe('goal down');
  });

  it('并发 refresh 只发一轮请求', async () => {
    let resolveGoals: (v: unknown) => void = () => {};
    vi.mocked(listGoals).mockReturnValue(
      new Promise((resolve) => {
        resolveGoals = resolve;
      }) as never,
    );
    vi.mocked(todoClient.list).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
    } as never);
    vi.mocked(scheduledClient.list).mockResolvedValue([] as never);

    const first = useUnifiedTaskStore.getState().refresh();
    const second = useUnifiedTaskStore.getState().refresh();
    resolveGoals({ items: [], total: 0, limit: 200, offset: 0 });
    await Promise.all([first, second]);

    expect(listGoals).toHaveBeenCalledTimes(1);
  });
});
