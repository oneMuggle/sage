import { beforeEach, describe, expect, it, vi } from 'vitest';

// Same mocking scheme as commandRoutes.prompts.test.ts — stub only default fetch.
vi.mock('node-fetch', async () => {
  const actual = await vi.importActual<typeof import('node-fetch')>('node-fetch');
  return { ...actual, default: vi.fn() };
});

import nodeFetch from 'node-fetch';
import { invokeBackend } from '../invoke';

const mockedFetch = nodeFetch as unknown as ReturnType<typeof vi.fn>;

describe('scheduled IPC envelope', () => {
  beforeEach(() => mockedFetch.mockReset());

  it('scheduled_create_task unwraps { input } → flat body', async () => {
    mockedFetch.mockResolvedValueOnce({ ok: true, status: 201, json: async () => ({ id: '42' }) });

    // 前端 scheduledClient.create(input) 实际调用:
    //   invoke('scheduled_create_task', { input })
    // 后端 CreateTaskIn 是扁平 Pydantic 模型(name/type/schedule/... 顶层字段)。
    // body mapper 必须把 { input: {...} } 拆成 {...}。
    await invokeBackend(
      'scheduled_create_task',
      {
        input: {
          name: '每日汇报',
          type: 'recurring',
          schedule: { kind: 'recurring', cron: '0 9 * * *' },
          session_id: 'session-1',
          content: '汇报进度',
          enabled: true,
          mode: 'execute',
        },
      },
      'http://127.0.0.1:8765',
    );

    const [url, init] = mockedFetch.mock.calls[0] as [string, { method: string; body: string }];
    expect(url).toBe('http://127.0.0.1:8765/api/v1/scheduled/tasks');
    expect(init.method).toBe('POST');
    // 关键: body 不应再有 input 这一层嵌套。camelToSnakeKeys 会把 mode 等原样保留。
    const body = JSON.parse(init.body);
    expect(body).not.toHaveProperty('input');
    expect(body).toMatchObject({
      name: '每日汇报',
      type: 'recurring',
      session_id: 'session-1',
      content: '汇报进度',
      enabled: true,
      mode: 'execute',
    });
    expect(body.schedule).toEqual({ kind: 'recurring', cron: '0 9 * * *' });
  });

  it('scheduled_update_task unwraps { id, changes } → id in path, changes in body', async () => {
    mockedFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({}) });

    // 前端 scheduledClient.update(id, changes) 实际调用:
    //   invoke('scheduled_update_task', { id, changes })
    // 后端 UpdateTaskIn 是 extra="forbid" 的扁平模型 —— 把 { id, changes } 直接
    // POST 会触发 422(id 不在模型字段中)。body mapper 必须剥掉 id 与 changes 外壳。
    await invokeBackend(
      'scheduled_update_task',
      {
        id: 'task-42',
        changes: {
          name: '改名的任务',
          enabled: false,
          mode: 'execute',
        },
      },
      'http://127.0.0.1:8765',
    );

    const [url, init] = mockedFetch.mock.calls[0] as [string, { method: string; body: string }];
    expect(url).toBe('http://127.0.0.1:8765/api/v1/scheduled/tasks/task-42');
    expect(init.method).toBe('PATCH');
    const body = JSON.parse(init.body);
    // body 里不应该再嵌套 changes，也不应该把 id 写进 body (URL path 已经带了)
    expect(body).not.toHaveProperty('id');
    expect(body).not.toHaveProperty('changes');
    expect(body).toEqual({
      name: '改名的任务',
      enabled: false,
      mode: 'execute',
    });
  });

  it('scheduled_update_task: mode=execute 透传到后端 body,不触发 422', async () => {
    mockedFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({}) });

    await invokeBackend(
      'scheduled_update_task',
      { id: 'abc', changes: { mode: 'execute' } },
      'http://127.0.0.1:8765',
    );

    const [, init] = mockedFetch.mock.calls[0] as [string, { body: string }];
    const body = JSON.parse(init.body);
    expect(body.mode).toBe('execute');
    expect(Object.keys(body)).toEqual(['mode']);
  });
});
