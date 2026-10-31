import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  compileLatex,
  getLatexCapabilities,
  latexdiff,
  type LatexCompileResult,
  type LatexDiffResult,
} from '../../../shared/api/latexApi';
import { LatexBuildPanel } from '../LatexBuildPanel';

vi.mock('../../../shared/api/latexApi', () => ({
  getLatexCapabilities: vi.fn(),
  compileLatex: vi.fn(),
  latexdiff: vi.fn(),
}));

const mockedCaps = vi.mocked(getLatexCapabilities);
const mockedCompile = vi.mocked(compileLatex);
const mockedDiff = vi.mocked(latexdiff);

const COMPILED: LatexCompileResult = {
  ok: true,
  engine: 'latexmk',
  pdf_path: 'paper/main.pdf',
  returncode: 0,
};

const DIFFED: LatexDiffResult = {
  ok: true,
  diff_path: 'paper/main-diff.tex',
  latexdiff_available: true,
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('LatexBuildPanel', () => {
  it('loads capabilities, compiles and generates a redline', async () => {
    mockedCaps.mockResolvedValue({
      engines: [{ name: 'latexmk', path: '/usr/bin/latexmk' }],
      latexdiff: '/usr/bin/latexdiff',
    });
    mockedCompile.mockResolvedValue(COMPILED);
    mockedDiff.mockResolvedValue(DIFFED);

    render(<LatexBuildPanel workspacePath="/ws" />);

    await waitFor(() => expect(mockedCaps).toHaveBeenCalled());
    expect(screen.getAllByText(/latexmk/).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByTestId('latex-compile-path'), {
      target: { value: 'paper/main.tex' },
    });
    fireEvent.change(screen.getByTestId('latex-compile-output'), {
      target: { value: 'main.pdf' },
    });
    fireEvent.click(screen.getByTestId('latex-compile-run'));

    await waitFor(() =>
      expect(mockedCompile).toHaveBeenCalledWith(
        '/ws',
        '/ws/paper/main.tex',
        'main.pdf',
        undefined,
      ),
    );
    expect(screen.getAllByText(/paper\/main\.pdf/).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByTestId('latex-diff-original'), {
      target: { value: 'paper/v1.tex' },
    });
    fireEvent.change(screen.getByTestId('latex-diff-revised'), {
      target: { value: 'paper/v2.tex' },
    });
    fireEvent.change(screen.getByTestId('latex-diff-output'), {
      target: { value: 'diff.tex' },
    });
    fireEvent.click(screen.getByTestId('latex-diff-run'));

    await waitFor(() =>
      expect(mockedDiff).toHaveBeenCalledWith(
        '/ws',
        '/ws/paper/v1.tex',
        '/ws/paper/v2.tex',
        'diff.tex',
        false,
        undefined,
      ),
    );
    expect(screen.getAllByText(/paper\/main-diff\.tex/).length).toBeGreaterThan(0);
  });

  it('reports an error without a bound workspace', async () => {
    render(<LatexBuildPanel workspacePath={null} />);

    fireEvent.change(screen.getByTestId('latex-compile-path'), {
      target: { value: 'paper/main.tex' },
    });
    fireEvent.click(screen.getByTestId('latex-compile-run'));

    await waitFor(() =>
      expect(screen.getByText(/请先绑定工作区/)).toBeInTheDocument(),
    );
    expect(mockedCompile).not.toHaveBeenCalled();
  });
});
