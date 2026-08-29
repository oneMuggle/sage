// tests/electron/tiers/stub/deep/orchestration.spec.ts
import { test, expect, request } from '@playwright/test';
import { launchElectronWithStub, type ElectronWithStub } from '../../../helpers/electron-launcher';
import type { APIRequestContext } from '@playwright/test';

test.describe('orchestration deep', () => {
  let app: ElectronWithStub['app'];
  let page: ElectronWithStub['page'];
  let stub: ElectronWithStub['stub'];
  let apiCtx: APIRequestContext;
  test.beforeAll(async () => {
    ({ app, page, stub } = await launchElectronWithStub());
    apiCtx = await request.newContext({ baseURL: stub.url });
  });
  test.afterAll(async () => {
    await app?.close();
    stub?.stop();
    await apiCtx?.dispose();
  });

  test('创建编排后显示 planner、executor、reviewer lanes', async () => {
    await page.goto('http://localhost:1420/#/orchestration');
    await page.locator('[data-testid="orch-create"]').click();
    await page.locator('[data-testid="orch-plan"]').fill('Research memory tiers');
    await page.locator('[data-testid="orch-submit"]').click();

    const lanes = page.locator('[data-testid^="lane-lane_"]');
    // lane cards expose the bound agent ID; assert each role rather than only
    // counting cards, so arbitrary three lanes cannot satisfy this contract.
    await expect(lanes).toHaveCount(3);
    await expect(lanes.filter({ hasText: /planner_/ })).toHaveCount(1);
    await expect(lanes.filter({ hasText: /executor_/ })).toHaveCount(1);
    await expect(lanes.filter({ hasText: /reviewer_/ })).toHaveCount(1);
  });

  test.skip('reviewer 拒绝触发重试', async () => {
    // stub 固定返回 ready lanes，不模拟 reviewer rejection 或 retry 状态。

    await page.goto('http://localhost:1420/#/orchestration');
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
