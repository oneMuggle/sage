/**
 * WordStyleTemplateLibrary (M2) — 模板库「样式模板 / 版式」分区测试。
 *
 * 覆盖：预设只读列表 + 工作区模板行（默认徽章/来源标签）、设为默认、
 * 两段式删除、加载失败透出错误。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import type { WordStyleTemplate } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { WordStyleTemplateLibrary } from '../WordStyleTemplateLibrary';

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listWordStylePresets: vi.fn(),
    listWordStyleTemplates: vi.fn(),
    activateWordStyleTemplate: vi.fn(),
    clearDefaultWordStyleTemplate: vi.fn(),
    deleteWordStyleTemplate: vi.fn(),
  },
}));

const mockedPresets = vi.mocked(officeApi.listWordStylePresets);
const mockedTemplates = vi.mocked(officeApi.listWordStyleTemplates);
const mockedActivate = vi.mocked(officeApi.activateWordStyleTemplate);
const mockedClearDefault = vi.mocked(officeApi.clearDefaultWordStyleTemplate);
const mockedDelete = vi.mocked(officeApi.deleteWordStyleTemplate);

const TEMPLATE = {
  id: 'tpl-1',
  workspace_path: '/ws',
  name: '公文版式',
  format_spec: {},
  source_kind: 'preset',
  source_ref: 'report',
  is_default: false,
  created_at: 0,
  updated_at: 0,
} as unknown as WordStyleTemplate;

function renderLibrary() {
  render(
    <I18nProvider defaultLocale="zh">
      <WordStyleTemplateLibrary workspacePath="/ws" />
    </I18nProvider>,
  );
}

describe('WordStyleTemplateLibrary', () => {
  beforeEach(() => {
    mockedPresets.mockReset();
    mockedTemplates.mockReset();
    mockedActivate.mockReset();
    mockedClearDefault.mockReset();
    mockedDelete.mockReset();
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

  it('renders presets and workspace templates with source and default badge', async () => {
    mockedTemplates.mockResolvedValue({
      ok: true,
      workspace_path: '/ws',
      templates: [{ ...TEMPLATE, is_default: true }],
    });
    renderLibrary();

    expect(await screen.findByTestId('office-word-style-preset-report')).toHaveTextContent(
      '工作报告',
    );
    expect(screen.getByTestId('office-word-style-template-tpl-1')).toHaveTextContent('公文版式');
    expect(screen.getByTestId('office-word-style-default-badge-tpl-1')).toHaveTextContent('默认');
    expect(screen.getByTestId('office-word-style-template-tpl-1')).toHaveTextContent('预设');
    expect(mockedTemplates).toHaveBeenCalledWith('/ws');
  });

  it('activates a template and reflects the new default after reload', async () => {
    mockedTemplates
      .mockResolvedValueOnce({ ok: true, workspace_path: '/ws', templates: [TEMPLATE] })
      .mockResolvedValueOnce({
        ok: true,
        workspace_path: '/ws',
        templates: [{ ...TEMPLATE, is_default: true }],
      });
    mockedActivate.mockResolvedValue({ ok: true, template: { ...TEMPLATE, is_default: true } });
    renderLibrary();

    fireEvent.click(await screen.findByTestId('office-word-style-activate-tpl-1'));

    await waitFor(() => expect(mockedActivate).toHaveBeenCalledWith('tpl-1', '/ws'));
    expect(await screen.findByTestId('office-word-style-default-badge-tpl-1')).toBeInTheDocument();
    expect(screen.getByTestId('office-word-style-message')).toHaveTextContent('公文版式');
  });

  it('clears the workspace default template', async () => {
    mockedTemplates
      .mockResolvedValueOnce({
        ok: true,
        workspace_path: '/ws',
        templates: [{ ...TEMPLATE, is_default: true }],
      })
      .mockResolvedValueOnce({ ok: true, workspace_path: '/ws', templates: [TEMPLATE] });
    mockedClearDefault.mockResolvedValue({ ok: true, workspace_path: '/ws' });
    renderLibrary();

    fireEvent.click(await screen.findByTestId('office-word-style-clear-default'));

    await waitFor(() => expect(mockedClearDefault).toHaveBeenCalledWith('/ws'));
    await waitFor(() =>
      expect(screen.queryByTestId('office-word-style-default-badge-tpl-1')).toBeNull(),
    );
  });

  it('deletes a template only after the second click', async () => {
    mockedDelete.mockResolvedValue({ ok: true, template_id: 'tpl-1', workspace_path: '/ws' });
    mockedTemplates
      .mockResolvedValueOnce({ ok: true, workspace_path: '/ws', templates: [TEMPLATE] })
      .mockResolvedValueOnce({ ok: true, workspace_path: '/ws', templates: [] });
    renderLibrary();

    const deleteBtn = await screen.findByTestId('office-word-style-delete-tpl-1');
    fireEvent.click(deleteBtn);
    expect(mockedDelete).not.toHaveBeenCalled();
    expect(deleteBtn).toHaveTextContent('确认删除');

    fireEvent.click(deleteBtn);
    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith('tpl-1', '/ws'));
    expect(await screen.findByTestId('office-word-style-empty')).toBeInTheDocument();
  });

  it('shows the load error when listing fails', async () => {
    mockedTemplates.mockRejectedValue(new Error('boom'));
    renderLibrary();

    expect(await screen.findByTestId('office-word-style-error')).toHaveTextContent('boom');
    expect(screen.getByTestId('office-word-style-empty')).toBeInTheDocument();
  });
});
