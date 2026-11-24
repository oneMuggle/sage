/**
 * WordStyleApplyDialog (M2 · D4) — 已有文档「套用样式」对话框测试。
 *
 * 覆盖：预设/模板下拉（默认标记）、dry-run 预览的来源透传与变更统计、
 * 应用（副本 / 覆写）、失败错误透出。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import type { WordStyleTemplate } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { WordStyleApplyDialog } from '../WordStyleApplyDialog';

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listWordStylePresets: vi.fn(),
    listWordStyleTemplates: vi.fn(),
    applyWordStyle: vi.fn(),
  },
}));

const mockedPresets = vi.mocked(officeApi.listWordStylePresets);
const mockedTemplates = vi.mocked(officeApi.listWordStyleTemplates);
const mockedApply = vi.mocked(officeApi.applyWordStyle);

const MANAGED_PATH = '/ws/office/word/42/report.docx';

const TEMPLATE = {
  id: 'tpl-1',
  workspace_path: '/ws',
  name: '公文版式',
  format_spec: {},
  source_kind: 'preset',
  source_ref: 'report',
  is_default: true,
  created_at: 0,
  updated_at: 0,
} as unknown as WordStyleTemplate;

const PREVIEW_RESULT = {
  ok: true,
  dry_run: true,
  saved: false,
  output_path: null,
  styles_changed: [{ style: 'Heading 1', field: 'font_size', before: 12, after: 16 }],
  direct_runs_cleared: 0,
  warnings: ['caption 样式只对生成期题注生效'],
};

function renderDialog(onApplied = vi.fn()) {
  render(
    <I18nProvider defaultLocale="zh">
      <WordStyleApplyDialog
        workspacePath="/ws"
        managedPath={MANAGED_PATH}
        onApplied={onApplied}
        onClose={vi.fn()}
      />
    </I18nProvider>,
  );
  return onApplied;
}

describe('WordStyleApplyDialog', () => {
  beforeEach(() => {
    mockedPresets.mockReset();
    mockedTemplates.mockReset();
    mockedApply.mockReset();
    mockedPresets.mockResolvedValue({
      ok: true,
      presets: [{ id: 'report', name: '工作报告', description: '' }],
    });
    mockedTemplates.mockResolvedValue({
      ok: true,
      workspace_path: '/ws',
      templates: [TEMPLATE],
    });
  });

  it('renders preset and workspace template options with the default marker', async () => {
    renderDialog();

    expect(await screen.findByRole('option', { name: '工作报告' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '公文版式 · 默认' })).toBeInTheDocument();
    expect(mockedTemplates).toHaveBeenCalledWith('/ws');
  });

  it('previews changes with a dry run and shows the diff summary', async () => {
    mockedApply.mockResolvedValue(PREVIEW_RESULT);
    renderDialog();

    const select = await screen.findByTestId('office-word-style-apply-source');
    await screen.findByRole('option', { name: '工作报告' });
    fireEvent.change(select, { target: { value: 'preset:report' } });
    fireEvent.click(screen.getByTestId('office-word-style-apply-preview'));

    await waitFor(() =>
      expect(mockedApply).toHaveBeenCalledWith(
        expect.objectContaining({
          workspace_path: '/ws',
          file_path: MANAGED_PATH,
          format_spec_preset: 'report',
          clear_direct_formatting: false,
          dry_run: true,
        }),
      ),
    );
    const stats = await screen.findByTestId('office-word-style-apply-preview-result');
    expect(stats).toHaveTextContent('样式变更: 1');
    expect(stats).toHaveTextContent('Heading 1 · font_size: 12 → 16');
    expect(stats).toHaveTextContent('caption 样式只对生成期题注生效');
  });

  it('applies a template with overwrite and notifies the parent', async () => {
    mockedApply.mockResolvedValue({
      ...PREVIEW_RESULT,
      dry_run: false,
      saved: true,
      output_path: MANAGED_PATH,
    });
    const onApplied = renderDialog();

    const select = await screen.findByTestId('office-word-style-apply-source');
    await screen.findByRole('option', { name: '公文版式 · 默认' });
    fireEvent.change(select, { target: { value: 'template:tpl-1' } });
    fireEvent.click(screen.getByTestId('office-word-style-apply-overwrite'));
    fireEvent.click(screen.getByTestId('office-word-style-apply-run'));

    await waitFor(() =>
      expect(mockedApply).toHaveBeenCalledWith(
        expect.objectContaining({
          file_path: MANAGED_PATH,
          style_template_id: 'tpl-1',
          overwrite: true,
          dry_run: false,
        }),
      ),
    );
    expect(await screen.findByTestId('office-word-style-apply-result-saved')).toHaveTextContent(
      '已覆写原文件',
    );
    expect(onApplied).toHaveBeenCalled();
  });

  it('reports the saved copy path when overwrite is off', async () => {
    mockedApply.mockResolvedValue({
      ...PREVIEW_RESULT,
      dry_run: false,
      saved: true,
      output_path: '/ws/office/word/42/report-styled.docx',
    });
    renderDialog();

    const select = await screen.findByTestId('office-word-style-apply-source');
    await screen.findByRole('option', { name: '工作报告' });
    fireEvent.change(select, { target: { value: 'preset:report' } });
    fireEvent.click(screen.getByTestId('office-word-style-apply-run'));

    const saved = await screen.findByTestId('office-word-style-apply-result-saved');
    expect(saved).toHaveTextContent('已另存副本');
    expect(saved).toHaveTextContent('/ws/office/word/42/report-styled.docx');
  });

  it('surfaces apply failures inline', async () => {
    mockedApply.mockRejectedValue(new Error('boom'));
    renderDialog();

    const select = await screen.findByTestId('office-word-style-apply-source');
    await screen.findByRole('option', { name: '工作报告' });
    fireEvent.change(select, { target: { value: 'preset:report' } });
    fireEvent.click(screen.getByTestId('office-word-style-apply-run'));

    expect(await screen.findByTestId('office-word-style-apply-error')).toHaveTextContent(
      '套用失败: boom',
    );
  });
});
