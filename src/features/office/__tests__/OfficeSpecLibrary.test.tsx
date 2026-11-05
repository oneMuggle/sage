import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import type { OfficeSpecDocument } from '../../../shared/api/officeSpecTypes';
import type { WordRuleExtractionResult } from '../../../shared/api/wordAuditTypes';
import { OfficeSpecLibrary } from '../OfficeSpecLibrary';

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listSpecs: vi.fn(),
    activateSpec: vi.fn(),
    clearDefaultSpec: vi.fn(),
    deleteSpec: vi.fn(),
    extractSpec: vi.fn(),
    createSpec: vi.fn(),
    bindDocSpec: vi.fn(),
  },
}));

const mockedList = vi.mocked(officeApi.listSpecs);
const mockedActivate = vi.mocked(officeApi.activateSpec);
const mockedClear = vi.mocked(officeApi.clearDefaultSpec);
const mockedDelete = vi.mocked(officeApi.deleteSpec);
const mockedExtract = vi.mocked(officeApi.extractSpec);
const mockedCreate = vi.mocked(officeApi.createSpec);
const mockedBind = vi.mocked(officeApi.bindDocSpec);

const SPEC_DEFAULT: OfficeSpecDocument = {
  id: 'spec-a',
  workspace_path: '/ws',
  name: '期刊投稿规范',
  source_file_path: 'docs/spec.docx',
  source_content_hash: null,
  rulepack_id: 'journal-spec',
  is_default: true,
  created_at: 1762300000000,
  updated_at: 1762300000000,
};

const SPEC_PLAIN: OfficeSpecDocument = {
  ...SPEC_DEFAULT,
  id: 'spec-b',
  name: '课程论文规范',
  source_file_path: null,
  rulepack_id: 'course-pack',
  is_default: false,
};

const EXTRACTION: WordRuleExtractionResult = {
  ok: true,
  source_path: 'docs/spec.docx',
  file_type: 'spec',
  llm_used: false,
  pack: {
    id: 'journal-spec',
    name: '期刊规范',
    version: '1.0',
    rules: [
      {
        id: 'page.margins',
        title: '页边距',
        category: 'page',
        severity: 'error',
        kind: 'page.margins',
        params: { top_cm: 2.54 },
        source: 'spec.docx 第 1 段',
        fixable: true,
        fix_hint: '设置页边距',
      },
    ],
  },
  candidates: [],
  conflicts: [],
  warnings: [],
  summary: { rules: 1, candidates: 0, conflicts: 0, warnings: 0 },
};

beforeEach(() => {
  mockedList.mockResolvedValue({
    ok: true,
    workspace_path: '/ws',
    specs: [SPEC_DEFAULT, SPEC_PLAIN],
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('OfficeSpecLibrary', () => {
  it('asks for a workspace when none is bound', () => {
    render(<OfficeSpecLibrary workspacePath={null} />);
    expect(screen.getByTestId('office-spec-no-workspace')).toBeInTheDocument();
    expect(mockedList).not.toHaveBeenCalled();
  });

  it('lists specs with a default badge and actions', async () => {
    render(<OfficeSpecLibrary workspacePath="/ws" />);

    expect(await screen.findByTestId('office-spec-row-spec-a')).toBeInTheDocument();
    expect(screen.getByTestId('office-spec-default-badge-spec-a')).toHaveTextContent(
      '工作区默认',
    );
    expect(screen.queryByTestId('office-spec-activate-spec-a')).toBeNull();
    expect(screen.getByTestId('office-spec-activate-spec-b')).toBeInTheDocument();
    expect(screen.getByTestId('office-spec-clear-default')).toBeInTheDocument();
    expect(mockedList).toHaveBeenCalledWith({ workspacePath: '/ws' });
  });

  it('activates a spec and refreshes the list', async () => {
    mockedActivate.mockResolvedValue({ ...SPEC_PLAIN, is_default: true });
    render(<OfficeSpecLibrary workspacePath="/ws" />);

    fireEvent.click(await screen.findByTestId('office-spec-activate-spec-b'));

    await waitFor(() => {
      expect(mockedActivate).toHaveBeenCalledWith('spec-b', '/ws');
    });
    await waitFor(() => {
      expect(mockedList).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByTestId('office-spec-message')).toHaveTextContent(
      '已设为工作区默认规范书',
    );
  });

  it('deletes only after a second confirmation click', async () => {
    mockedDelete.mockResolvedValue({
      ok: true,
      spec_id: 'spec-a',
      workspace_path: '/ws',
    });
    render(<OfficeSpecLibrary workspacePath="/ws" />);

    const deleteButton = await screen.findByTestId('office-spec-delete-spec-a');
    fireEvent.click(deleteButton);
    expect(mockedDelete).not.toHaveBeenCalled();
    expect(deleteButton).toHaveTextContent('确认删除');

    fireEvent.click(deleteButton);
    await waitFor(() => {
      expect(mockedDelete).toHaveBeenCalledWith('spec-a', '/ws');
    });
  });

  it('extracts a draft and saves it as a new spec', async () => {
    mockedExtract.mockResolvedValue(EXTRACTION);
    mockedCreate.mockResolvedValue({
      ok: true,
      spec: { ...SPEC_PLAIN, id: 'spec-new', name: '期刊规范（导入）' },
      rulepack: EXTRACTION.pack,
    });
    render(<OfficeSpecLibrary workspacePath="/ws" />);

    fireEvent.change(await screen.findByTestId('office-spec-extract-path'), {
      target: { value: 'docs/spec.docx' },
    });
    fireEvent.click(screen.getByTestId('office-spec-extract-run'));

    await waitFor(() => {
      expect(mockedExtract).toHaveBeenCalledWith({
        workspace_path: '/ws',
        file_path: '/ws/docs/spec.docx',
        use_llm: false,
      });
    });

    expect(await screen.findByTestId('office-spec-draft')).toBeInTheDocument();
    expect(screen.getByTestId('office-spec-draft-name')).toHaveValue(
      '期刊规范（导入）',
    );

    fireEvent.click(screen.getByTestId('office-spec-draft-save'));

    await waitFor(() => {
      expect(mockedCreate).toHaveBeenCalledWith(
        expect.objectContaining({
          workspace_path: '/ws',
          name: '期刊规范（导入）',
          pack: EXTRACTION.pack,
          is_default: false,
        }),
      );
    });
  });

  it('binds a spec to a document', async () => {
    mockedBind.mockResolvedValue({
      ok: true,
      doc_id: 'doc-1',
      spec_id: 'spec-a',
      effective_spec: SPEC_DEFAULT,
    });
    render(<OfficeSpecLibrary workspacePath="/ws" />);

    fireEvent.change(await screen.findByTestId('office-spec-bind-doc-id'), {
      target: { value: 'doc-1' },
    });
    fireEvent.change(screen.getByTestId('office-spec-bind-spec-id'), {
      target: { value: 'spec-a' },
    });
    fireEvent.click(screen.getByTestId('office-spec-bind-run'));

    await waitFor(() => {
      expect(mockedBind).toHaveBeenCalledWith('doc-1', {
        workspacePath: '/ws',
        specId: 'spec-a',
      });
    });
    expect(await screen.findByTestId('office-spec-bind-message')).toHaveTextContent(
      '已绑定「期刊投稿规范」',
    );
  });

  it('clears the workspace default spec', async () => {
    mockedClear.mockResolvedValue({ ok: true, default: null });
    render(<OfficeSpecLibrary workspacePath="/ws" />);

    fireEvent.click(await screen.findByTestId('office-spec-clear-default'));

    await waitFor(() => {
      expect(mockedClear).toHaveBeenCalledWith('/ws');
    });
    expect(await screen.findByTestId('office-spec-message')).toHaveTextContent(
      '已清除工作区默认规范书',
    );
  });
});
