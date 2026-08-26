// tests/electron/tiers/stub/deep/orchestration.spec.ts
import { test, expect, request } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test.describe('orchestration deep', () => {
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

  test('planner → executor → reviewer 全流程', async () => {
    await page.goto('/orchestration');
    await page.locator('[data-testid="orch-create"]').click();
    await page.locator('[data-testid="orch-plan"]').fill('Research memory tiers');
    await page.locator('[data-testid="orch-submit"]').click();

    // 验证 3 个 lane 出现
    await expect(page.locator('[data-testid^="lane-"]')).toHaveCount(3);

    // 通过 stub API 拿 run_id 验证状态
    const list = await apiCtx.get('/api/v1/orchestration/runs').catch(() => null);
    // stub 当前没有 list endpoint；至少 get single run
    const rid = await page.locator('[data-testid="orch-run-id"]').first().textContent();
    const run = await apiCtx.get(`/api/v1/orchestration/runs/${rid}`);
    expect(run.ok()).toBeTruthy();
  });

  test('reviewer 拒绝触发重试', async () => {
    // 调用 stub draft 拒绝 endpoint（stub 应在 signals 中返回 user_correction 类型）
    await page.goto('/orchestration');
    await page.locator('[data-testid="orch-create"]').click();
    await page.locator('[data-testid="orch-plan"]').fill('trigger reviewer rejection');
    await page.locator('[data-testid="orch-submit"]').click();
    await expect(page.locator('[data-testid="lane-reviewer-rejected"]')).toBeVisible({
      timeout: 10_000,
    });
  });

  test('用户审批 token 后 run 进入 approved', async () => {
    const create = await apiCtx.post('/api/v1/orchestration/runs', {
      data: { session_id: 's1', plan: 'p' },
    });
    const rid = (await create.json()).run_id;
    const approve = await apiCtx.post(`/api/v1/orchestration/runs/${rid}/approve`, {
      data: { token: 'user_token_1' },
    });
    expect(approve.ok()).toBeTruthy();
    const run = await apiCtx.get(`/api/v1/orchestration/runs/${rid}`);
    expect((await run.json()).approval_token).toBe('user_token_1');
  });
});
