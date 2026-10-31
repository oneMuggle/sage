import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  extractLatexProject,
  type LatexProjectExtractResult,
} from '../../../shared/api/latexApi';
import { LatexProjectImportPanel } from '../LatexProjectImportPanel';

vi.mock('../../../shared/api/latexApi', () => ({
  extractLatexProject: vi.fn(),
}));

const mockedExtract = vi.mocked(extractLatexProject);

const EXTRACTED: LatexProjectExtractResult = {
  ok: true,
  project_dir: 'imported',
  main_file: 'imported/paper/main.tex',
  main_candidates: ['imported/paper/main.tex'],
  files_count: 3,
  bytes_written: 2048,
  warnings: [],
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('LatexProjectImportPanel', () => {
  it('extracts a project zip and shows the detected main file', async () => {
    mockedExtract.mockResolvedValue(EXTRACTED);

    render(<LatexProjectImportPanel workspacePath="/ws" />);

    fireEvent.change(screen.getByTestId('latex-project-zip-path'), {
      target: { value: 'downloads/template.zip' },
    });
    fireEvent.change(screen.getByTestId('latex-project-output-dir'), {
      target: { value: 'imported' },
    });
    fireEvent.click(screen.getByTestId('latex-project-extract'));

    await waitFor(() =>
      expect(mockedExtract).toHaveBeenCalledWith(
        '/ws',
        '/ws/downloads/template.zip',
        'imported',
      ),
    );
    expect(screen.getByTestId('latex-project-result')).toHaveTextContent(
      'imported/paper/main.tex',
    );
    expect(screen.getByTestId('latex-project-result')).toHaveTextContent(
      '3 个文件',
    );
  });

  it('shows backend errors', async () => {
    mockedExtract.mockRejectedValue(new Error('输出目录已存在，拒绝覆盖'));

    render(<LatexProjectImportPanel workspacePath="/ws" />);

    fireEvent.change(screen.getByTestId('latex-project-zip-path'), {
      target: { value: 'template.zip' },
    });
    fireEvent.click(screen.getByTestId('latex-project-extract'));

    await waitFor(() =>
      expect(screen.getByText('输出目录已存在，拒绝覆盖')).toBeTruthy(),
    );
  });
});
