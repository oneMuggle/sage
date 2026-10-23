import { beforeEach, describe, expect, it, vi } from 'vitest';

// Same mocking scheme as invoke.test.ts: keep node-fetch's named exports real, stub only `fetch`.
vi.mock('node-fetch', async () => {
  const actual = await vi.importActual<typeof import('node-fetch')>('node-fetch');
  return { ...actual, default: vi.fn() };
});

import nodeFetch from 'node-fetch';
import { invokeBackend } from '../invoke';

const mockedFetch = nodeFetch as unknown as ReturnType<typeof vi.fn>;

describe('prompts_reorder (dropped by #857, restored)', () => {
  beforeEach(() => mockedFetch.mockReset());

  it('PUTs the new id order as ordered_ids', async () => {
    mockedFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({}) });
    // promptApi.reorder(ids) -> invoke('prompts_reorder', { orderedIds: ids })
    await invokeBackend(
      'prompts_reorder',
      { orderedIds: ['b', 'a', 'c'] },
      'http://127.0.0.1:8765',
    );
    const [url, init] = mockedFetch.mock.calls[0] as [string, { method: string; body: string }];
    expect(url).toBe('http://127.0.0.1:8765/api/v1/prompts/templates/reorder');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ ordered_ids: ['b', 'a', 'c'] });
  });
});
