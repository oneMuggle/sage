import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import { officeGenerateApi } from '../../../shared/api/officeGenerateApi';
import type { OfficeDocumentSummary, OfficeGenerateResult } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
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
  officeApi: { listTemplates: vi.fn() },
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
    mockedNl.mockReset();
    mockedChat.mockReset();
    mockedIterate.mockReset();
    mockedListTemplates.mockReset();
    mockedToastError.mockReset();
    mockedListTemplates.mockResolvedValue({ templates: [TEMPLATE] });
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
});
