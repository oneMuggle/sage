// tests/electron/tiers/stub/deep/memory.spec.ts
import { test, expect, request } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test.describe('memory deep', () => {
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

  test('三层各写入 + unified search 返回三层', async () => {
    for (const layer of ['episodic', 'semantic', 'working']) {
      const r = await apiCtx.post(`/api/v1/memory/${layer}`, {
        data: { session_id: 's1', content: `hello ${layer}` },
      });
      expect(r.ok()).toBeTruthy();
    }
    const r = await apiCtx.get('/api/v1/memory/search?q=hello');
    const data = await r.json();
    expect(data.episodic.length).toBeGreaterThanOrEqual(1);
    expect(data.semantic.length).toBeGreaterThanOrEqual(1);
    expect(data.working.length).toBeGreaterThanOrEqual(1);
  });

  test('按 layer 过滤', async () => {
    await apiCtx.post('/api/v1/memory/episodic', { data: { session_id: 's1', content: 'foo' } });
    await apiCtx.post('/api/v1/memory/semantic', { data: { session_id: 's1', content: 'foo' } });
    const r = await apiCtx.get('/api/v1/memory/search?q=foo&layer=episodic');
    const data = await r.json();
    expect(data.episodic.length).toBeGreaterThanOrEqual(1);
    expect(data.semantic).toHaveLength(0);
    expect(data.working).toHaveLength(0);
  });

  test('consolidate 返回 pending', async () => {
    const r = await apiCtx.post('/api/v1/memory/consolidate', { data: { session_id: 's1' } });
    expect((await r.json()).status).toBe('pending');
  });

  test('profile 返回 user_id + facts', async () => {
    const r = await apiCtx.get('/api/v1/memory/profile/user_42');
    const data = await r.json();
    expect(data.user_id).toBe('user_42');
    expect(Array.isArray(data.facts)).toBe(true);
  });
});
