import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import { officeGenerateApi } from '../../../shared/api/officeGenerateApi';
import type { OfficeDocumentSummary, OfficeGenerateResult } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useTaskCenterStore } from '../../task-center/taskCenterStore';
import { GenerateWorkspace } from '../GenerateWorkspace';

vi.mock('../officeProgress', () => ({ pollOfficeProgress: () => () => {} }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../../../shared/api/officeGenerateApi', () => ({
  officeGenerateApi: {
    generateFromNl: vi.fn(),
    generateFromTemplateChat: vi.fn(),
    iterateDocument: vi.fn(),
  },
}));
vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listTemplates: vi.fn(),
    templateThumbnail: vi.fn().mockResolvedValue({ ok: false }),
    listWordStylePresets: vi.fn(),
    listWordStyleTemplates: vi.fn(),
  },
}));

const mockedNl = vi.mocked(officeGenerateApi.generateFromNl);
const mockedChat = vi.mocked(officeGenerateApi.generateFromTemplateChat);
const mockedIterate = vi.mocked(officeGenerateApi.iterateDocument);
const mockedListTemplates = vi.mocked(officeApi.listTemplates);
const mockedToastError = vi.mocked(toast.error);

const WORD_DOC = {
  id: 'd1',
  workspace_path: '/ws',
  doc_type: 'word',
  original_filename: null,
  generated_filename: 'report.docx',
  status: 'generated',
  created_at: 0,
  updated_at: 0,
  metadata: { file_size_bytes: 10 },
  derived_from: null,
  archived_at: null,
} as unknown as OfficeDocumentSummary;

const RESULT = {
  output_path: '/ws/office/word/d2/out.docx',
  filename: 'out.docx',
  file_size_bytes: 42,
  summary: { ...WORD_DOC, id: 'd2', generated_filename: 'out.docx' },
} as OfficeGenerateResult;

const TEMPLATE = {
  id: 'weekly_report',
  name: '周报',
  description: '内置周报模板',
  doc_type: 'word' as const,
  placeholders: [],
  source: 'builtin' as const,
};

const STYLE_PRESET = { id: 'report', name: '工作报告', description: '' };

const STYLE_TEMPLATE = {
  id: 'tpl-1',
  workspace_path: '/ws',
  name: '公文版式',
  format_spec: {},
  source_kind: 'preset' as const,
  source_ref: 'report',
  is_default: true,
  created_at: 0,
  updated_at: 0,
};

function renderWorkspace() {
  const onGenerated = vi.fn();
  const onOpenDocument = vi.fn();
  render(
    <I18nProvider defaultLocale="zh">
      <GenerateWorkspace
        workspacePath="/ws"
        documents={[WORD_DOC]}
        onGenerated={onGenerated}
        onOpenDocument={onOpenDocument}
      />
    </I18nProvider>,
  );
  return { onGenerated, onOpenDocument };
}

describe('GenerateWorkspace', () => {
  beforeEach(() => {
    useTaskCenterStore.setState({ tasks: {}, delivery: null, shellStream: null });
    mockedNl.mockReset();
    mockedChat.mockReset();
    mockedIterate.mockReset();
    mockedListTemplates.mockReset();
    mockedToastError.mockReset();
    mockedListTemplates.mockResolvedValue({ templates: [TEMPLATE] });
    vi.mocked(officeApi.listWordStylePresets).mockReset();
    vi.mocked(officeApi.listWordStyleTemplates).mockReset();
    vi.mocked(officeApi.listWordStylePresets).mockResolvedValue({
      ok: true,
      presets: [STYLE_PRESET],
    });
    vi.mocked(officeApi.listWordStyleTemplates).mockResolvedValue({
      ok: true,
      workspace_path: '/ws',
      templates: [STYLE_TEMPLATE],
    });
  });

  it('renders four mode tabs and switches panels', () => {
    renderWorkspace();

    for (const mode of ['nl', 'reference', 'template', 'iterate']) {
      expect(screen.getByTestId(`office-generate-workspace-mode-${mode}`)).toBeInTheDocument();
    }

    fireEvent.click(screen.getByTestId('office-generate-workspace-mode-reference'));
    expect(screen.getByTestId('office-generate-workspace-ref-d1')).toBeInTheDocument();
  });

  it('submits an NL generation with a snake_case body', async () => {
    mockedNl.mockResolvedValue(RESULT);
    renderWorkspace();

    fireEvent.change(screen.getByTestId('office-generate-workspace-instruction'), {
      target: { value: '写一份周报' },
    });
    fireEvent.change(screen.getByTestId('office-generate-workspace-doc-type'), {
      target: { value: 'ppt' },
    });
    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    await waitFor(() => expect(mockedNl).toHaveBeenCalledTimes(1));
    expect(mockedNl).toHaveBeenCalledWith({
      task_id: expect.any(String),
      workspace_path: '/ws',
      instruction: '写一份周报',
      doc_type: 'ppt',
    });
    expect(
      await screen.findByTestId('office-generate-workspace-result-filename'),
    ).toHaveTextContent('out.docx');
  });

  it('passes reference_paths for the selected word documents', async () => {
    mockedNl.mockResolvedValue(RESULT);
    renderWorkspace();

    fireEvent.click(screen.getByTestId('office-generate-workspace-mode-reference'));
    fireEvent.click(screen.getByTestId('office-generate-workspace-ref-d1'));
    fireEvent.change(screen.getByTestId('office-generate-workspace-instruction'), {
      target: { value: '参考周报' },
    });
    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    await waitFor(() => expect(mockedNl).toHaveBeenCalledTimes(1));
    expect(mockedNl).toHaveBeenCalledWith({
      task_id: expect.any(String),
      workspace_path: '/ws',
      instruction: '参考周报',
      doc_type: 'word',
      reference_paths: ['/ws/office/word/d1/report.docx'],
    });
  });

  it('sends template chat with the selected template and message history', async () => {
    mockedChat.mockResolvedValue(RESULT);
    renderWorkspace();

    fireEvent.click(screen.getByTestId('office-generate-workspace-mode-template'));
    fireEvent.click(await screen.findByTestId('office-template-library-item-weekly_report'));
    fireEvent.change(screen.getByTestId('office-generate-workspace-chat-input'), {
      target: { value: '第 45 周' },
    });
    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    await waitFor(() => expect(mockedChat).toHaveBeenCalledTimes(1));
    expect(mockedChat).toHaveBeenCalledWith({
      task_id: expect.any(String),
      workspace_path: '/ws',
      template_id: 'weekly_report',
      messages: [{ role: 'user', content: '第 45 周' }],
    });
  });

  it('submits iterate with the managed document path', async () => {
    mockedIterate.mockResolvedValue(RESULT);
    renderWorkspace();

    fireEvent.click(screen.getByTestId('office-generate-workspace-mode-iterate'));
    fireEvent.click(screen.getByTestId('office-generate-workspace-iterate-d1'));
    fireEvent.change(screen.getByTestId('office-generate-workspace-instruction'), {
      target: { value: '更正式' },
    });
    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    await waitFor(() => expect(mockedIterate).toHaveBeenCalledTimes(1));
    expect(mockedIterate).toHaveBeenCalledWith({
      task_id: expect.any(String),
      workspace_path: '/ws',
      source_path: '/ws/office/word/d1/report.docx',
      instruction: '更正式',
    });
  });

  it('lists style presets and preselects the workspace default template for word', async () => {
    renderWorkspace();

    const select = await screen.findByTestId('office-generate-workspace-style');
    await waitFor(() => expect(select).toHaveValue('template:tpl-1'));
    expect(await screen.findByRole('option', { name: /工作报告/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /公文版式/ })).toBeInTheDocument();
    expect(officeApi.listWordStyleTemplates).toHaveBeenCalledWith('/ws');
  });

  it('passes the chosen style preset for word generation', async () => {
    mockedNl.mockResolvedValue(RESULT);
    renderWorkspace();

    const select = await screen.findByTestId('office-generate-workspace-style');
    await screen.findByRole('option', { name: /工作报告/ });
    fireEvent.change(select, { target: { value: 'preset:report' } });
    fireEvent.change(screen.getByTestId('office-generate-workspace-instruction'), {
      target: { value: '写一份报告' },
    });
    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    await waitFor(() => expect(mockedNl).toHaveBeenCalledTimes(1));
    expect(mockedNl).toHaveBeenCalledWith({
      task_id: expect.any(String),
      workspace_path: '/ws',
      instruction: '写一份报告',
      doc_type: 'word',
      format_spec_preset: 'report',
    });
  });

  it('forwards the preselected default style template when untouched', async () => {
    mockedNl.mockResolvedValue(RESULT);
    renderWorkspace();

    const select = await screen.findByTestId('office-generate-workspace-style');
    await waitFor(() => expect(select).toHaveValue('template:tpl-1'));
    fireEvent.change(screen.getByTestId('office-generate-workspace-instruction'), {
      target: { value: '写一份通知' },
    });
    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    await waitFor(() => expect(mockedNl).toHaveBeenCalledTimes(1));
    expect(mockedNl).toHaveBeenCalledWith({
      task_id: expect.any(String),
      workspace_path: '/ws',
      instruction: '写一份通知',
      doc_type: 'word',
      style_template_id: 'tpl-1',
    });
  });

  it('moves word generations into the delivery drawer with the style template id (M2 D5)', async () => {
    mockedNl.mockResolvedValue(RESULT);
    renderWorkspace();

    const select = await screen.findByTestId('office-generate-workspace-style');
    await waitFor(() => expect(select).toHaveValue('template:tpl-1'));
    fireEvent.change(screen.getByTestId('office-generate-workspace-instruction'), {
      target: { value: '写一份通知' },
    });
    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    await waitFor(() =>
      expect(useTaskCenterStore.getState().tasks['office:generate']?.status).toBe(
        'awaiting_approval',
      ),
    );
    const state = useTaskCenterStore.getState();
    expect(state.tasks['office:generate'].deliveryRef).toEqual({
      workspacePath: '/ws',
      filePath: RESULT.output_path,
      formatSpec: null,
      styleTemplateId: 'tpl-1',
    });
    expect(state.delivery).toEqual({ kind: 'office', entryId: 'office:generate' });
  });

  it('keeps non-word generations out of the delivery drawer (M2 D5)', async () => {
    mockedNl.mockResolvedValue(RESULT);
    renderWorkspace();

    await screen.findByTestId('office-generate-workspace-style');
    fireEvent.change(screen.getByTestId('office-generate-workspace-doc-type'), {
      target: { value: 'ppt' },
    });
    fireEvent.change(screen.getByTestId('office-generate-workspace-instruction'), {
      target: { value: '做一份 PPT' },
    });
    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    await waitFor(() => expect(mockedNl).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(useTaskCenterStore.getState().tasks['office:generate']).toBeUndefined(),
    );
    expect(useTaskCenterStore.getState().delivery).toBeNull();
  });

  it('hides the style dropdown for non-word document types', async () => {
    renderWorkspace();

    expect(await screen.findByTestId('office-generate-workspace-style')).toBeInTheDocument();
    fireEvent.change(screen.getByTestId('office-generate-workspace-doc-type'), {
      target: { value: 'excel' },
    });
    expect(screen.queryByTestId('office-generate-workspace-style')).not.toBeInTheDocument();
  });

  it('warns and skips the call when the instruction is empty', () => {
    renderWorkspace();

    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    expect(mockedToastError).toHaveBeenCalledWith('请填写生成要求');
    expect(mockedNl).not.toHaveBeenCalled();
  });

  it('shows an error toast when generation fails', async () => {
    mockedNl.mockRejectedValue(new Error('boom'));
    renderWorkspace();

    fireEvent.change(screen.getByTestId('office-generate-workspace-instruction'), {
      target: { value: 'x' },
    });
    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    await waitFor(() => expect(mockedToastError).toHaveBeenCalledWith('生成失败: boom'));
  });

  it('calls onGenerated after a successful run', async () => {
    mockedNl.mockResolvedValue(RESULT);
    const { onGenerated } = renderWorkspace();

    fireEvent.change(screen.getByTestId('office-generate-workspace-instruction'), {
      target: { value: 'x' },
    });
    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    await waitFor(() => expect(onGenerated).toHaveBeenCalledTimes(1));
  });

  it('does not report a generation failure when onGenerated rejects', async () => {
    mockedNl.mockResolvedValue(RESULT);
    const onGenerated = vi.fn().mockRejectedValue(new Error('refresh failed'));
    render(
      <I18nProvider defaultLocale="zh">
        <GenerateWorkspace workspacePath="/ws" documents={[WORD_DOC]} onGenerated={onGenerated} />
      </I18nProvider>,
    );

    fireEvent.change(screen.getByTestId('office-generate-workspace-instruction'), {
      target: { value: 'x' },
    });
    fireEvent.click(screen.getByTestId('office-generate-workspace-submit'));

    await waitFor(() => expect(onGenerated).toHaveBeenCalledTimes(1));
    // Flush the rejection microtask: a leaked catch would have fired by now.
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(mockedToastError).not.toHaveBeenCalled();
    expect(screen.getByTestId('office-generate-workspace-result-filename')).toHaveTextContent(
      'out.docx',
    );
  });
});
