// tests/electron/tiers/stub/deep/office-pdf-generate-preview.spec.ts
//
// Round-3 Office plan item N1 — PDF generate + preview flows on the /office
// page, exercised through the real Electron renderer in DEMO stub mode.
//
// Why demo mode: the tier-1 Python stub backend (stub_backend.py) only serves
// sessions/workspace/chat routes — it has no /office routes. The Office UI
// instead runs against the renderer-side demo registry
// (src/shared/api/demoInterceptors.ts), which stubs every office_* channel.
// Launching with SAGE_DEMO_MODE=1 flips electron/main.ts isDemoProcess(),
// which forwards `--sage-demo-mode=1` to the renderer so isDemoMode() is true
// from the first paint and demoInterceptors answers the UI calls.
//
// Assertion shapes mirror the ACTUAL demo stub responses:
//   - workspace_get  → binding /home/fz/sage-workspace (DEMO_WORKSPACE_PATH)
//   - office_list_documents → the 4 DEMO_OFFICE_DOCS rows
//   - office_pdf_read → DEMO_PDF_READ (2 pages: 检索策略与纳入排除标准 …)
//   - office_pdf_generate → demo handler (round-3 N1) appends a pdf row and
//     returns {output_path, filename, file_size_bytes, page_count: 2} → the
//     form toasts 生成成功 <filename> and the list gains a 5th row.
//
// The preview path avoids the native file picker entirely: the document list
// has no click-to-preview, so the spec drives the only demo-only route into
// OfficePreviewPanel — the row's 历史版本 panel (office_list_snapshots /
// office_restore_snapshot are stubbed) whose restore re-reads the document
// via readDocument → office_pdf_read.
import { test, expect } from '@playwright/test';
import { launchElectronWithStub, type ElectronWithStub } from '../../../helpers/electron-launcher';

const OFFICE_URL = 'http://localhost:1420/#/office';

/** The PDF demo doc shipped in DEMO_OFFICE_DOCS (of-4). */
const DEMO_PDF_ROW_TITLE = '检索策略与纳入排除标准.pdf';

test.describe('office pdf generate + preview (demo stub mode)', () => {
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
    // workspace_get demo stub pre-binds the demo workspace — without it the
    // page renders its empty state and every flow below is unreachable.
    await expect(page.getByTestId('office-workspace-path')).toHaveText('/home/fz/sage-workspace');
    // The demo document list settled (4 seeded rows).
    await expect(page.getByTestId('office-document-list').locator('li')).toHaveCount(4);
  });

  test('01: PDF tab generate succeeds, list gains a pdf row', async () => {
    // 2026-11 IA restructure: the generate form (and its PPT/WORD/EXCEL/PDF
    // format tabs) moved from the default "文档处理" panel into the dedicated
    // "文档生成" top-level tab. Switch to it before looking for the PDF button.
    await page.getByTestId('office-tab-generate').click();

    // P3 generate workspace: doc type is a <select>, not separate buttons.
    await page.getByTestId('office-generate-workspace-doc-type').selectOption('pdf');

    // P3 generate workspace: single instruction textarea replaces filename/title/paragraphs.
    await page
      .getByTestId('office-generate-workspace-instruction')
      .fill('生成一份关于智能体年度趋势的 PDF 文档，包含多智能体编排和记忆系统两个章节。');

    await page.getByTestId('office-generate-workspace-submit').click();

    // demoBackendRequest intercepts POST /api/v1/office/generate/nl and returns
    // a synthetic payload → the workspace toasts 已生成 <filename>.
    await expect(page.locator('[data-sonner-toast]', { hasText: '已生成' })).toBeVisible();

    // P3 generate workspace: result panel shows the generated filename.
    const resultPanel = page.getByTestId('office-generate-workspace-result');
    await expect(
      resultPanel.getByTestId('office-generate-workspace-result-filename'),
    ).toContainText('.pdf');

    // The demo office_pdf_generate handler appends a row to the in-memory
    // document list, and onGenerated refreshed it → 4 seeded + 1 new.
    await page.getByTestId('office-tab-documents').click();
    const list = page.getByTestId('office-document-list');
    await expect(list.locator('li')).toHaveCount(5);
    await expect(list.locator('li').first()).toContainText('.pdf');
  });

  test('02: demo PDF row restores into the preview panel with 2 page cards', async () => {
    // "Select" the demo PDF row via its 历史版本 action (aria-label) — the
    // only in-demo path that fills the preview panel without the native
    // file picker.
    const pdfRow = page
      .getByTestId('office-document-list')
      .locator('li')
      .filter({ hasText: DEMO_PDF_ROW_TITLE });
    await expect(pdfRow).toHaveCount(1);
    await pdfRow.getByLabel('历史版本').click();

    const snapshotPanel = page.getByTestId('office-snapshot-panel');
    await expect(snapshotPanel).toBeVisible();
    // office_list_snapshots demo stub returns 2 snapshots for any doc.
    await expect(snapshotPanel.locator('li')).toHaveCount(2);

    // Two-step inline confirm on the FIRST snapshot row (the demo stub
    // lists 2 snapshots, each with its own 恢复到此版本 button):
    // 恢复到此版本 → 确认恢复.
    await snapshotPanel.getByRole('button', { name: '恢复到此版本' }).first().click();
    await snapshotPanel.getByRole('button', { name: '确认恢复' }).click();
    await expect(page.locator('[data-sonner-toast]', { hasText: '已恢复到此版本' })).toBeVisible();

    // The restore re-reads the document (office_pdf_read → DEMO_PDF_READ):
    // the preview panel shows the PDF with one card per page.
    const preview = page.getByTestId('office-preview-panel');
    await expect(preview).toBeVisible();
    await expect(preview.getByText(DEMO_PDF_ROW_TITLE)).toBeVisible();
    const pageCards = preview.locator('ol > li');
    await expect(pageCards).toHaveCount(2);
    await expect(pageCards.nth(0)).toContainText('第 1 页');
    await expect(pageCards.nth(0)).toContainText('检索策略与纳入排除标准');
    await expect(pageCards.nth(1)).toContainText('第 2 页');
    await expect(pageCards.nth(1)).toContainText('纳入标准');
  });
});
