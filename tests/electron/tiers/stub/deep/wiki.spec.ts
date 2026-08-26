// tests/electron/tiers/stub/deep/wiki.spec.ts
import { test, expect, request } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test.describe('wiki deep', () => {
  let app, stub, apiCtx;
  test.beforeAll(async () => {
    ({ app, stub } = await launchElectronWithStub());
    apiCtx = await request.newContext({ baseURL: stub.url });
  });
  test.afterAll(async () => {
    await app?.close();
    stub?.stop();
    await apiCtx?.dispose();
  });

  test('ingest → search 返回按 score 排序', async () => {
    await apiCtx.post('/api/v1/wiki/ingest', {
      data: { title: 'A', content: 'first doc' },
    });
    await apiCtx.post('/api/v1/wiki/ingest', {
      data: { title: 'B', content: 'second doc' },
    });
    const r = await apiCtx.post('/api/v1/wiki/search', {
      data: { query: 'doc', limit: 10 },
    });
    const data = await r.json();
    expect(data.total).toBeGreaterThanOrEqual(2);
    // 排序：score 递减
    for (let i = 0; i < data.items.length - 1; i++) {
      expect(data.items[i].score).toBeGreaterThanOrEqual(data.items[i + 1].score);
    }
  });

  test('extract 返回 title/body/links', async () => {
    const r = await apiCtx.post('/api/v1/wiki/extract', {
      data: { content: 'Hello world. This is Sage.' },
    });
    const data = await r.json();
    expect(data.title).toBeTruthy();
    expect(data.body).toContain('Sage');
    expect(Array.isArray(data.links)).toBe(true);
  });

  test('insights 返回 summary + tags', async () => {
    const create = await apiCtx.post('/api/v1/wiki/ingest', {
      data: { title: 'X', content: 'Y' },
    });
    const { doc_id } = await create.json();
    const ins = await apiCtx.get(`/api/v1/wiki/insights/${doc_id}`);
    const data = await ins.json();
    expect(data.summary).toBeTruthy();
    expect(Array.isArray(data.tags)).toBe(true);
  });

  test('deep research 返回 plan', async () => {
    const r = await apiCtx.post('/api/v1/wiki/deep-research', {
      data: { topic: 'memory tiers' },
    });
    const data = await r.json();
    expect(Array.isArray(data.steps)).toBe(true);
    expect(data.steps.length).toBeGreaterThanOrEqual(1);
  });
});
