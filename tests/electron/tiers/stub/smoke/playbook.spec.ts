import { test, expect } from '@playwright/test';

import { launchElectronWithStub } from '../../../helpers/electron-launcher';

interface RecordedAction {
  type: string;
  payload?: { moves?: Array<{ from: string; to: string }> };
}

interface RecordedActionsResponse {
  actions: RecordedAction[][];
}

test('playbook smoke: 归类批量移动后可撤销', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  try {
    await page.evaluate(() => {
      window.location.hash = '#/projects/governance/p1';
    });
    await page.waitForSelector('[data-testid="playbook-card"]', { timeout: 20_000 });
    await page.waitForSelector('[data-testid="playbook-unclassified"]', {
      timeout: 20_000,
    });
    await expect(page.locator('[data-testid="playbook-stage-proposal"]')).toContainText('开题');

    await page.locator('[data-testid="playbook-select-all"]').click();
    await page.locator('[data-testid="playbook-batch-move"]').click();

    await expect(page.getByText('已批量移动 2 个文件（可撤销）')).toBeVisible({
      timeout: 10_000,
    });
    const undoButton = page.locator('[data-testid="playbook-undo-batch"]');
    await expect(undoButton).toBeVisible({ timeout: 10_000 });

    await undoButton.click();
    await expect(page.getByText('已撤销上次批量移动')).toBeVisible({ timeout: 10_000 });
    await expect(undoButton).toHaveCount(0, { timeout: 10_000 });

    const response = await fetch(`${stub.url}/api/v1/__stub/playbook-actions`);
    const recorded = (await response.json()) as RecordedActionsResponse;
    expect(recorded.actions).toHaveLength(2);
    expect(recorded.actions[0][0].type).toBe('batch_move');
    expect(recorded.actions[0][0].payload?.moves).toEqual([
      { from: '开题报告.md', to: '01_开题/开题报告.md' },
      { from: '论文初稿.docx', to: '03_成果/论文初稿.docx' },
    ]);
    expect(recorded.actions[1][0].type).toBe('undo_last_batch_move');
  } finally {
    await app.close();
    stub.stop();
  }
});
