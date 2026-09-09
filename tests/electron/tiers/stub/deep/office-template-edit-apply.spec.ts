// tests/electron/tiers/stub/deep/office-template-edit-apply.spec.ts
//
// Round-3 Office plan item N1 — 从模板创建 → 编辑预览 → 确认应用, the full
// Word authoring + in-page edit loop on /office, through the real Electron
// renderer in DEMO stub mode (SAGE_DEMO_MODE=1 → renderer
// demoInterceptors answers every office_* channel; see
// office-pdf-generate-preview.spec.ts for why demo mode is the tier-1 stub
// for Office).
//
// Demo stub responses the assertions rely on:
//   - office_list_templates      → DEMO_OFFICE_TEMPLATES (builtin weekly_report first word entry)
//   - office_templates_instantiate → persists a generated row (unshifted → first in list),
//                                  returns filled_count / unfilled_placeholders
//   - office_list_snapshots / office_restore_snapshot → 2 fake snapshots, restore ok
//   - office_word_read           → DEMO_WORD_READ (summary stays of-1: the read
//                                  stub ignores the path, so the preview panel /
//                                  edit dialog target of-1 — known demo simplification)
//   - office_update_preview      → one generic change per op (replace_text: before=find, after=replace)
//   - office_doc_update          → {ok, summary, self_check:{ok:true}}, doc.status → 'edited'
//
// The edit dialog needs a filled preview panel; the list has no
// click-to-preview, so the spec re-uses the demo-only route via the row's
// 历史版本 panel restore (same as the PDF spec).
import { test, expect } from '@playwright/test';
import { launchElectronWithStub, type ElectronWithStub } from '../../../helpers/electron-launcher';

const OFFICE_URL = 'http://localhost:1420/#/office';

const TEMPLATE_FILENAME = '周报-E2E-覆盖.docx';
/** New doc row's filename in the list right after 创建. */
const TEMPLATE_ROW_TITLE = TEMPLATE_FILENAME;
/** of-1 — the summary office_word_read always returns in demo mode. */
const DEMO_WORD_ROW_TITLE = '文献综述报告-大模型医学应用.docx';

test.describe('office template create → edit preview → apply (demo stub mode)', () => {
  let app: ElectronWithStub['app'];
  let page: ElectronWithStub['page'];
  let stub: ElectronWithStub['stub'];

  test.beforeAll(async () => {
    ({ app, page, stub } = await launchElectronWithStub({
      env: { SAGE_DEMO_MODE: '1' },
    }));
  });

  test.afterAll(async () => {
    await app?.close();
    stub?.stop();
  });

  test.beforeEach(async () => {
    await page.goto(OFFICE_URL);
    await expect(page.getByTestId('office-page')).toBeVisible();
    await expect(page.getByTestId('office-workspace-path')).toHaveText('/home/fz/sage-workspace');
    await expect(page.getByTestId('office-document-list').locator('li')).toHaveCount(4);
  });

  test('instantiate a builtin template, restore it into preview, apply a replace_text edit', async () => {
    // ── 1. Word tab → 从模板创建 ──────────────────────────────────────
    await page.getByRole('button', { name: 'WORD', exact: true }).click();
    await page.getByTestId('office-word-mode-template').click();

    // The picker lazily fetches office_list_templates; the first builtin
    // word template in the demo registry is weekly_report (周报模板).
    const picker = page.getByTestId('office-template-picker');
    await expect(picker).toBeVisible();
    await page.getByTestId('office-template-option-weekly_report').click();

    // A picked template renders one field per placeholder (testid IS the
    // input/textarea element): author is a text input, this_week a
    // rich_text textarea.
    await expect(page.getByTestId('office-template-fields')).toBeVisible();
    await page.getByTestId('office-template-input-author').fill('E2E 测试员');
    await page
      .getByTestId('office-template-input-this_week')
      .fill('- 完成 office e2e 覆盖\n- 修复评审意见');

    await page.getByTestId('office-generate-filename').fill(TEMPLATE_FILENAME);

    // ── 2. 创建 → success toast + list gains the doc ─────────────────
    await page.getByTestId('office-generate-submit').click();
    await expect(page.locator('[data-sonner-toast]', { hasText: '已从模板创建' })).toBeVisible();

    // onGenerated refreshed the list; instantiate unshifts its row.
    const list = page.getByTestId('office-document-list');
    const newRow = list.locator('li').filter({ hasText: TEMPLATE_ROW_TITLE });
    await expect(newRow).toHaveCount(1);
    await expect(newRow).toContainText('已生成');

    // ── 3. Select → preview via the 历史版本 restore path ────────────
    await newRow.getByLabel('历史版本').click();
    const snapshotPanel = page.getByTestId('office-snapshot-panel');
    await expect(snapshotPanel).toBeVisible();
    await snapshotPanel.getByRole('button', { name: '恢复到此版本' }).first().click();
    await snapshotPanel.getByRole('button', { name: '确认恢复' }).click();
    await expect(page.locator('[data-sonner-toast]', { hasText: '已恢复到此版本' })).toBeVisible();

    // office_word_read returns DEMO_WORD_READ, whose summary is of-1 —
    // the preview (and therefore the edit dialog) targets that doc.
    const preview = page.getByTestId('office-preview-panel');
    await expect(preview).toBeVisible();
    await expect(preview.getByText(DEMO_WORD_ROW_TITLE)).toBeVisible();

    // ── 4. 编辑预览 → compose a replace_text op ──────────────────────
    await page.getByTestId('office-edit-preview-button').click();
    const dialog = page.getByTestId('office-edit-preview-dialog');
    await expect(dialog).toBeVisible();

    await page.getByTestId('office-edit-find').fill('Med-PaLM 2');
    await page.getByTestId('office-edit-replace').fill('GPT-4');
    await page.getByTestId('office-edit-preview-submit').click();

    // ── 5. 预览变更 → diff row visible ───────────────────────────────
    const result = page.getByTestId('office-edit-result');
    await expect(result).toBeVisible();
    const changeRow = page.getByTestId('office-edit-change');
    await expect(changeRow).toHaveCount(1);
    await expect(changeRow).toContainText('replace_text');
    await expect(changeRow).toContainText('原文');
    await expect(changeRow).toContainText('Med-PaLM 2');
    await expect(changeRow).toContainText('替换后');
    await expect(changeRow).toContainText('GPT-4');

    // ── 6. 确认应用 → applied panel + toast + list reflects 已编辑 ───
    await page.getByTestId('office-edit-apply').click();
    await expect(page.getByTestId('office-edit-applied')).toBeVisible();
    await expect(page.getByTestId('office-edit-applied')).toContainText('已应用编辑');
    await expect(page.getByTestId('office-edit-self-check')).toContainText('自检通过');
    await expect(page.locator('[data-sonner-toast]', { hasText: '已应用编辑' })).toBeVisible();

    // onApplied refreshed the list: office_doc_update flipped of-1's
    // status to 'edited' (已编辑) in the demo store.
    const editedRow = list.locator('li').filter({ hasText: DEMO_WORD_ROW_TITLE });
    await expect(editedRow).toContainText('已编辑');
  });
});
