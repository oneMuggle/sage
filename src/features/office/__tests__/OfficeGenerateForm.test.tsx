/**
 * OfficeGenerateForm tests — office parity batch 3 (item 3.2 从模板创建).
 *
 * Coverage:
 *  - template picker: builtin 内置 / workspace 工作区 source badges.
 *  - dynamic fields per placeholder type: text/date → text input (+ date
 *    hint), table/rich_text → textarea (+ rich hint), image → note only,
 *    no input.
 *  - instantiate success: builtin resolves by template_id, workspace by
 *    workspace_template (filename); image placeholders excluded and blank
 *    fields skipped in `data`; success toast + onGenerated refresh +
 *    cleared fields.
 *  - failure: backend message surfaces in the error toast, list is NOT
 *    refreshed and the form is preserved.
 *
 * officeApi is mocked — the free-form generate methods are exercised
 * nowhere here (they keep their Phase 1.4 behavior).
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockListTemplates = vi.fn();
const mockInstantiate = vi.fn();
const mockOnGenerated = vi.fn();

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listTemplates: (...args: unknown[]) => mockListTemplates(...args),
    instantiateTemplate: (...args: unknown[]) => mockInstantiate(...args),
  },
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import type { OfficeTemplateMeta } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { OfficeGenerateForm } from '../OfficeGenerateForm';

const toastMock = toast as unknown as {
  success: ReturnType<typeof vi.fn>;
  error: ReturnType<typeof vi.fn>;
};

const BUILTIN_TEMPLATE: OfficeTemplateMeta = {
  id: 'weekly_report',
  name: '周报模板',
  description: '标准周报模板',
  doc_type: 'word',
  placeholders: [
    { name: 'author', type: 'text', description: '作者姓名' },
    { name: 'report_date', type: 'date', description: '报告日期' },
    { name: 'this_week', type: 'rich_text' },
    { name: 'metrics_table', type: 'table' },
    { name: 'logo', type: 'image' },
  ],
  source: 'builtin',
};

const WORKSPACE_TEMPLATE: OfficeTemplateMeta = {
  id: '项目周报',
  name: '项目周报',
  doc_type: 'word',
  placeholders: [{ name: 'title', type: 'text' }],
  source: 'workspace',
  filename: '项目周报.docx',
};

function renderForm() {
  return render(
    <I18nProvider defaultLocale="zh">
      <OfficeGenerateForm workspacePath="/tmp/ws" onGenerated={mockOnGenerated} />
    </I18nProvider>,
  );
}

/** WORD tab → 从模板创建 → wait for the picker to resolve. */
async function openTemplatePicker() {
  renderForm();
  fireEvent.click(screen.getByText('WORD'));
  fireEvent.click(screen.getByTestId('office-word-mode-template'));
  await screen.findByTestId('office-template-option-weekly_report');
}

describe('OfficeGenerateForm — template picker (item 3.2)', () => {
  beforeEach(() => {
    mockListTemplates.mockReset();
    mockInstantiate.mockReset();
    mockOnGenerated.mockReset();
    toastMock.success.mockReset();
    toastMock.error.mockReset();
    mockListTemplates.mockResolvedValue({
      templates: [BUILTIN_TEMPLATE, WORKSPACE_TEMPLATE],
    });
    mockInstantiate.mockResolvedValue({
      output_path: '/tmp/ws/周报模板-2026-09-10.docx',
      filename: '周报模板-2026-09-10.docx',
      file_size_bytes: 20480,
      filled_count: 2,
      unfilled_placeholders: [],
    });
  });

  it('renders builtin and workspace templates with source badges', async () => {
    await openTemplatePicker();

    expect(mockListTemplates).toHaveBeenCalledWith('/tmp/ws');
    expect(screen.getByTestId('office-template-option-weekly_report')).toBeInTheDocument();
    expect(screen.getByTestId('office-template-option-项目周报')).toBeInTheDocument();

    const badges = screen.getAllByTestId('office-template-source');
    expect(badges.map((b) => b.textContent)).toEqual(['内置', '工作区']);
  });

  it('renders dynamic fields per placeholder type (text/date input, table/rich_text textarea, image note only)', async () => {
    await openTemplatePicker();
    fireEvent.click(screen.getByTestId('office-template-option-weekly_report'));

    // text + date → text inputs; date carries the format hint.
    expect(screen.getByTestId('office-template-input-author').tagName).toBe('INPUT');
    const dateInput = screen.getByTestId('office-template-input-report_date');
    expect(dateInput.tagName).toBe('INPUT');
    expect(screen.getAllByText('日期格式 YYYY-MM-DD').length).toBeGreaterThan(0);

    // table + rich_text → textareas with the rich-variable hint.
    expect(screen.getByTestId('office-template-input-this_week').tagName).toBe('TEXTAREA');
    expect(screen.getByTestId('office-template-input-metrics_table').tagName).toBe('TEXTAREA');
    expect(screen.getAllByText(/支持 \{\{ \}\} 富文本或表格变量/).length).toBe(2);

    // image → note only, no input rendered.
    expect(screen.getByTestId('office-template-field-logo')).toBeInTheDocument();
    expect(screen.queryByTestId('office-template-input-logo')).toBeNull();
    expect(screen.getByText('仅模板内图片变量，文本留空跳过')).toBeInTheDocument();
  });

  it('instantiates a builtin template by template_id, refreshes the list and clears fields', async () => {
    await openTemplatePicker();
    fireEvent.click(screen.getByTestId('office-template-option-weekly_report'));

    fireEvent.change(screen.getByTestId('office-template-input-author'), {
      target: { value: '张三' },
    });
    fireEvent.change(screen.getByTestId('office-template-input-report_date'), {
      target: { value: '2026-09-10' },
    });
    fireEvent.click(screen.getByTestId('office-generate-submit'));

    await waitFor(() => {
      expect(mockInstantiate).toHaveBeenCalledTimes(1);
    });
    const req = mockInstantiate.mock.calls[0][0] as Record<string, unknown>;
    expect(req.workspace_path).toBe('/tmp/ws');
    expect(req.template_id).toBe('weekly_report');
    expect(req).not.toHaveProperty('workspace_template');
    // Default filename = template name + today's date.
    expect(String(req.filename)).toMatch(/^周报模板-\d{4}-\d{2}-\d{2}\.docx$/);
    // Blanks are skipped; image placeholders never contribute.
    expect(req.data).toEqual({ author: '张三', report_date: '2026-09-10' });

    await waitFor(() => {
      expect(toastMock.success).toHaveBeenCalledWith(expect.stringContaining('已从模板创建'));
    });
    expect(mockOnGenerated).toHaveBeenCalledTimes(1);
    // Form cleared after success.
    await waitFor(() => {
      expect(
        (screen.getByTestId('office-template-input-author') as HTMLInputElement).value,
      ).toBe('');
    });
  });

  it('instantiates a workspace template by workspace_template filename', async () => {
    await openTemplatePicker();
    fireEvent.click(screen.getByTestId('office-template-option-项目周报'));

    fireEvent.change(screen.getByTestId('office-template-input-title'), {
      target: { value: '第 38 周项目周会' },
    });
    fireEvent.click(screen.getByTestId('office-generate-submit'));

    await waitFor(() => {
      expect(mockInstantiate).toHaveBeenCalledTimes(1);
    });
    const req = mockInstantiate.mock.calls[0][0] as Record<string, unknown>;
    expect(req.workspace_template).toBe('项目周报.docx');
    expect(req).not.toHaveProperty('template_id');
    expect(req.data).toEqual({ title: '第 38 周项目周会' });
  });

  it('toasts the backend message on failure without refreshing or clearing the form', async () => {
    mockInstantiate.mockRejectedValueOnce(new Error('模板变量不足: author'));
    await openTemplatePicker();
    fireEvent.click(screen.getByTestId('office-template-option-weekly_report'));
    fireEvent.change(screen.getByTestId('office-template-input-author'), {
      target: { value: '张三' },
    });
    fireEvent.click(screen.getByTestId('office-generate-submit'));

    await waitFor(() => {
      expect(toastMock.error).toHaveBeenCalledWith(
        expect.stringContaining('创建失败'),
      );
    });
    expect(toastMock.error).toHaveBeenCalledWith(expect.stringContaining('模板变量不足: author'));
    expect(mockOnGenerated).not.toHaveBeenCalled();
    // Failure preserves the composed form.
    expect((screen.getByTestId('office-template-input-author') as HTMLInputElement).value).toBe(
      '张三',
    );
  });
});
