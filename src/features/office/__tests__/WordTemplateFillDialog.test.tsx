import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { OfficeDocumentSummary } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { WordTemplateFillDialog } from '../WordTemplateFillDialog';

const mocks = vi.hoisted(() => ({
  listTemplates: vi.fn(),
  analyzeProfile: vi.fn(),
  fillProfile: vi.fn(),
}));

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: { listTemplates: mocks.listTemplates },
}));

vi.mock('../../../shared/api/officeWordTemplateApi', () => ({
  officeWordTemplateApi: {
    analyzeProfile: mocks.analyzeProfile,
    fillProfile: mocks.fillProfile,
  },
}));

function makeDoc(
  id: string,
  filename: string,
  overrides: Partial<OfficeDocumentSummary> = {},
): OfficeDocumentSummary {
  return {
    id,
    doc_type: 'word',
    original_filename: filename,
    generated_filename: filename,
    status: 'parsed',
    created_at: 0,
    updated_at: 0,
    metadata: { file_size_bytes: 1024 },
    derived_from: null,
    archived_at: null,
    ...overrides,
  };
}

const profile = {
  ok: true,
  kind: 'word-template-profile' as const,
  source_path: 'office/word/doc-1/合同.docx',
  slots: [
    {
      name: '客户名称',
      kind: 'content_control',
      type: 'text' as const,
      required: true,
      description: null,
      current_value: '示例公司',
      confidence: 0.9,
      anchor: null,
    },
    {
      name: '公司logo',
      kind: 'placeholder',
      type: 'image' as const,
      required: false,
      description: null,
      current_value: null,
      confidence: 0.9,
      anchor: null,
    },
  ],
  warnings: [],
  summary: { slots: 2, kinds: { content_control: 1, placeholder: 1 }, has_jinja_control: false },
};

const fillResult = {
  ok: true,
  template_path: 'office/word/doc-1/合同.docx',
  output_path: 'office/word/doc-1/合同-filled.docx',
  filename: '合同-filled.docx',
  filled_count: 2,
  unfilled_slots: [],
  residual_placeholders: [],
  jinja_rendered: true,
  images_rendered: 1,
  warnings: [],
};

function renderDialog(
  overrides: {
    documents?: OfficeDocumentSummary[];
    workspacePath?: string | null;
    onFilled?: (absolutePath: string) => void | Promise<void>;
    onClose?: () => void;
  } = {},
) {
  return render(
    <I18nProvider defaultLocale="zh">
      <WordTemplateFillDialog
        isOpen
        onClose={overrides.onClose ?? (() => {})}
        workspacePath={overrides.workspacePath === undefined ? '/ws' : overrides.workspacePath}
        documents={overrides.documents ?? [makeDoc('doc-1', '合同.docx')]}
        onFilled={overrides.onFilled}
      />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listTemplates.mockResolvedValue({ templates: [] });
});

describe('WordTemplateFillDialog', () => {
  it('shows the empty hint when there are no Word candidates', async () => {
    renderDialog({ documents: [] });

    await waitFor(() =>
      expect(screen.getByTestId('office-word-template-empty')).toHaveTextContent(
        '暂无可用的 Word 模板',
      ),
    );
  });

  it('analyzes the picked document via its workspace-relative path', async () => {
    mocks.analyzeProfile.mockResolvedValue(profile);
    renderDialog();

    fireEvent.change(screen.getByTestId('office-word-template-select'), {
      target: { value: 'doc:doc-1' },
    });

    await waitFor(() =>
      expect(mocks.analyzeProfile).toHaveBeenCalledWith({
        workspace_path: '/ws',
        file_path: 'office/word/doc-1/合同.docx',
      }),
    );
    expect(await screen.findByTestId('office-word-template-slot-客户名称')).toBeInTheDocument();
    // 默认输出名取模板 stem + -filled.docx
    expect(screen.getByTestId('office-word-template-output')).toHaveValue('合同-filled.docx');
    // 必填槽位未填 → 运行按钮禁用
    expect(screen.getByTestId('office-word-template-run')).toBeDisabled();
  });

  it('filters workspace templates to Word files and analyzes them', async () => {
    mocks.listTemplates.mockResolvedValue({
      templates: [
        {
          id: 'ws:模板.docx',
          name: '模板.docx',
          doc_type: 'word',
          placeholders: [],
          source: 'workspace',
          filename: '模板.docx',
        },
        {
          id: 'builtin:1',
          name: '内置',
          doc_type: 'word',
          placeholders: [],
          source: 'builtin',
        },
        {
          id: 'ws:表.xlsx',
          name: '表.xlsx',
          doc_type: 'excel',
          placeholders: [],
          source: 'workspace',
          filename: '表.xlsx',
        },
      ],
    });
    mocks.analyzeProfile.mockResolvedValue(profile);
    renderDialog({ documents: [] });

    const select = (await screen.findByTestId('office-word-template-select')) as HTMLSelectElement;
    await waitFor(() => expect(select.options).toHaveLength(2));
    // 首个 option 是“请选择模板…”占位项
    expect(Array.from(select.options).map((option) => option.value)).toEqual(['', 'tpl:模板.docx']);

    fireEvent.change(select, { target: { value: 'tpl:模板.docx' } });
    await waitFor(() =>
      expect(mocks.analyzeProfile).toHaveBeenCalledWith({
        workspace_path: '/ws',
        file_path: 'office/templates/模板.docx',
      }),
    );
  });

  it('separates text data from image paths and reports the fill result', async () => {
    mocks.analyzeProfile.mockResolvedValue(profile);
    mocks.fillProfile.mockResolvedValue(fillResult);
    const onFilled = vi.fn();
    renderDialog({ onFilled });

    fireEvent.change(screen.getByTestId('office-word-template-select'), {
      target: { value: 'doc:doc-1' },
    });
    fireEvent.change(await screen.findByTestId('office-word-template-slot-客户名称'), {
      target: { value: '示例公司' },
    });
    fireEvent.change(screen.getByTestId('office-word-template-slot-公司logo'), {
      target: { value: 'office/logo.png' },
    });

    const run = screen.getByTestId('office-word-template-run');
    await waitFor(() => expect(run).toBeEnabled());
    fireEvent.click(run);

    await waitFor(() =>
      expect(mocks.fillProfile).toHaveBeenCalledWith({
        workspace_path: '/ws',
        template_path: 'office/word/doc-1/合同.docx',
        output_filename: '合同-filled.docx',
        data: { 客户名称: '示例公司' },
        images: { 公司logo: 'office/logo.png' },
      }),
    );
    expect(await screen.findByTestId('office-word-template-filled-count')).toHaveTextContent(
      '已填充 2 个槽位',
    );

    fireEvent.click(screen.getByTestId('office-word-template-import'));
    await waitFor(() =>
      expect(onFilled).toHaveBeenCalledWith('/ws/office/word/doc-1/合同-filled.docx'),
    );
  });

  it('keeps the run button disabled until required slots are filled', async () => {
    mocks.analyzeProfile.mockResolvedValue(profile);
    renderDialog();

    fireEvent.change(screen.getByTestId('office-word-template-select'), {
      target: { value: 'doc:doc-1' },
    });
    await screen.findByTestId('office-word-template-slot-客户名称');
    expect(screen.getByTestId('office-word-template-run')).toBeDisabled();

    fireEvent.change(screen.getByTestId('office-word-template-slot-客户名称'), {
      target: { value: '示例公司' },
    });
    expect(screen.getByTestId('office-word-template-run')).toBeEnabled();
  });

  it('surfaces analyze and fill failures in the dialog', async () => {
    mocks.analyzeProfile.mockRejectedValueOnce(new Error('analyze-boom'));
    renderDialog();

    fireEvent.change(screen.getByTestId('office-word-template-select'), {
      target: { value: 'doc:doc-1' },
    });
    expect(await screen.findByTestId('office-word-template-analyze-error')).toHaveTextContent(
      'analyze-boom',
    );

    mocks.analyzeProfile.mockResolvedValue(profile);
    mocks.fillProfile.mockRejectedValueOnce(new Error('fill-boom'));
    fireEvent.change(screen.getByTestId('office-word-template-select'), {
      target: { value: 'doc:doc-1' },
    });
    fireEvent.change(await screen.findByTestId('office-word-template-slot-客户名称'), {
      target: { value: '示例公司' },
    });
    const run = screen.getByTestId('office-word-template-run');
    await waitFor(() => expect(run).toBeEnabled());
    fireEvent.click(run);

    expect(await screen.findByTestId('office-word-template-fill-error')).toHaveTextContent(
      'fill-boom',
    );
  });
});
