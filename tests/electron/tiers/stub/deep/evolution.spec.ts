// tests/electron/tiers/stub/deep/evolution.spec.ts
import { test, expect, request } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test.describe('evolution deep', () => {
  let app, page, stub, apiCtx;
  test.beforeAll(async () => {
    ({ app, page, stub } = await launchElectronWithStub());
    apiCtx = await request.newContext({ baseURL: stub.url });
  });
  test.afterAll(async () => {
    await app?.close();
    stub?.stop();
    await apiCtx?.dispose();
  });

  test('signals 列表包含 seed', async () => {
    const r = await apiCtx.get('/api/v1/evolution/signals');
    const data = await r.json();
    expect(data.signals.length).toBeGreaterThanOrEqual(1);
    expect(data.signals[0]).toHaveProperty('id');
    expect(data.signals[0]).toHaveProperty('type');
    expect(data.signals[0]).toHaveProperty('strength');
  });

  test('draft 流程：创建 → queue 出现 → approve → 状态变更', async () => {
    const sigs = (await (await apiCtx.get('/api/v1/evolution/signals')).json()).signals;
    const create = await apiCtx.post('/api/v1/evolution/draft', {
      data: { signal_ids: [sigs[0].id] },
    });
    const draft = await create.json();
    expect(draft.id).toMatch(/^draft_/);
    expect(draft.status).toBe('pending');

    const queue = await (await apiCtx.get('/api/v1/evolution/queue')).json();
    expect(queue.drafts.some((d) => d.id === draft.id)).toBe(true);

    await apiCtx.post(`/api/v1/evolution/approve/${draft.id}`);

    const queue2 = await (await apiCtx.get('/api/v1/evolution/queue')).json();
    const updated = queue2.drafts.find((d) => d.id === draft.id);
    expect(updated.status).toBe('approved');
  });

  test('scheduler status 返回合法字段', async () => {
    const r = await apiCtx.get('/api/v1/evolution/scheduler/status');
    const data = await r.json();
    expect(['idle', 'running', 'stopped']).toContain(data.state);
    expect(typeof data.last_run_at_ms).toBe('number');
    expect(typeof data.next_run_at_ms).toBe('number');
  });
});
