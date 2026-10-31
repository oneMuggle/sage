import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  analyzeLatexTemplate,
  fillLatexTemplate,
  type LatexFillResult,
  type LatexTemplateProfile,
} from '../../../shared/api/latexApi';
import { LatexTemplatePanel } from '../LatexTemplatePanel';

vi.mock('../../../shared/api/latexApi', () => ({
  analyzeLatexTemplate: vi.fn(),
  fillLatexTemplate: vi.fn(),
}));

const mockedAnalyze = vi.mocked(analyzeLatexTemplate);
const mockedFill = vi.mocked(fillLatexTemplate);

const PROFILE: LatexTemplateProfile = {
  ok: true,
  kind: 'latex-template',
  source_path: 'paper/main.tex',
  document_class: 'article',
  document_options: [],
  packages: ['geometry'],
  macros: {},
  style: {},
  metadata: {},
  slots: [
    {
      name: 'title',
      kind: 'command_arg',
      type: 'text',
      required: true,
      description: '文档标题',
      current_value: 'Old Title',
      confidence: 1,
    },
    {
      name: 'author',
      kind: 'command_arg',
      type: 'list',
      required: true,
      description: '作者',
      current_value: 'Alice',
      confidence: 1,
    },
  ],
  warnings: [],
  includes: ['paper/main.tex'],
};

const FILL: LatexFillResult = {
  ok: true,
  template_path: 'paper/main.tex',
  output_path: 'paper/main-filled.tex',
  filename: 'main-filled.tex',
  filled_count: 2,
  unfilled_slots: [],
  validation: { ok: true, issues: [] },
  warnings: [],
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('LatexTemplatePanel', () => {
  it('analyzes a template and fills slots', async () => {
    mockedAnalyze.mockResolvedValue(PROFILE);
    mockedFill.mockResolvedValue(FILL);

    render(<LatexTemplatePanel workspacePath="/ws" />);

    fireEvent.change(screen.getByTestId('latex-template-path'), {
      target: { value: 'paper/main.tex' },
    });
    fireEvent.click(screen.getByTestId('latex-template-analyze'));

    await waitFor(() => expect(screen.getByTestId('latex-slot-title')).toBeInTheDocument());
    expect(mockedAnalyze).toHaveBeenCalledWith('/ws', '/ws/paper/main.tex');

    fireEvent.change(screen.getByTestId('latex-slot-title'), {
      target: { value: 'New Title' },
    });
    fireEvent.change(screen.getByTestId('latex-slot-author'), {
      target: { value: 'Alice, Bob' },
    });
    fireEvent.click(screen.getByTestId('latex-template-fill'));

    await waitFor(() => expect(screen.getByTestId('latex-fill-result')).toBeInTheDocument());
    expect(mockedFill).toHaveBeenCalledWith('/ws', '/ws/paper/main.tex', 'main-filled.tex', {
      title: 'New Title',
      author: ['Alice', 'Bob'],
    });
    expect(screen.getByText(/main-filled\.tex/)).toBeInTheDocument();
  });

  it('reports an error without a bound workspace', async () => {
    render(<LatexTemplatePanel workspacePath={null} />);

    fireEvent.change(screen.getByTestId('latex-template-path'), {
      target: { value: 'paper/main.tex' },
    });
    fireEvent.click(screen.getByTestId('latex-template-analyze'));

    await waitFor(() => expect(screen.getByText(/请先绑定工作区/)).toBeInTheDocument());
    expect(mockedAnalyze).not.toHaveBeenCalled();
  });
});
