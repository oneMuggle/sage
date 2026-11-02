import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  checkLatexCompliance,
  listLatexProfiles,
  loadLatexProfile,
  type LatexComplianceResult,
  type LatexProfileRecord,
} from '../../../shared/api/latexApi';
import { LatexCompliancePanel } from '../LatexCompliancePanel';

vi.mock('../../../shared/api/latexApi', () => ({
  checkLatexCompliance: vi.fn(),
  listLatexProfiles: vi.fn(),
  loadLatexProfile: vi.fn(),
}));

const mockedCheck = vi.mocked(checkLatexCompliance);
const mockedList = vi.mocked(listLatexProfiles);
const mockedLoad = vi.mocked(loadLatexProfile);

const RESULT: LatexComplianceResult = {
  ok: false,
  tex_path: 'paper/main.tex',
  pdf_path: 'paper/main.pdf',
  profile: {
    required_sections: ['Introduction', 'Conclusion'],
    required_metadata: ['title'],
    allowed_page_sizes: ['A4'],
    required_min_pages: null,
    required_max_pages: null,
    require_embedded_fonts: true,
    min_image_dpi: 150,
    forbidden_commands: [],
  },
  checks: [
    {
      id: 'tex.sections',
      label: '必需章节',
      status: 'fail',
      message: '1 个问题',
      rule_ids: ['LATEX-SECTION-REQUIRED'],
    },
    {
      id: 'pdf.fonts',
      label: '字体嵌入',
      status: 'pass',
      message: '',
      rule_ids: [],
    },
  ],
  issues: [
    {
      source: 'tex',
      rule_id: 'LATEX-SECTION-REQUIRED',
      severity: 'error',
      category: 'structure',
      message: '缺少必需章节: Conclusion',
      fix_hint: '添加 Conclusion 章节',
      anchor: { file: 'paper/main.tex', line: 1 },
    },
  ],
  summary: {
    count: 1,
    severity: { error: 1, warning: 0, info: 0 },
    categories: { structure: 1 },
  },
};

const RECORD: LatexProfileRecord = {
  name: 'ieee-2026',
  source: 'guidelines.pdf',
  evidence: [],
  updated_at: '2026-10-31T09:00:00+00:00',
  profile: {
    required_sections: ['Introduction', 'Conclusion'],
    required_metadata: ['title'],
    allowed_page_sizes: ['A4'],
    required_min_pages: 8,
    required_max_pages: 20,
    require_embedded_fonts: true,
    min_image_dpi: 300,
    forbidden_commands: ['write18'],
  },
};

afterEach(() => {
  vi.clearAllMocks();
});

beforeEach(() => {
  mockedList.mockResolvedValue({ profiles: [], warnings: [] });
});

describe('LatexCompliancePanel', () => {
  it('runs a compliance check and renders checks/issues', async () => {
    mockedCheck.mockResolvedValue(RESULT);

    render(<LatexCompliancePanel workspacePath="/ws" />);

    fireEvent.change(screen.getByTestId('latex-compliance-tex'), {
      target: { value: 'paper/main.tex' },
    });
    fireEvent.change(screen.getByTestId('latex-compliance-pdf'), {
      target: { value: 'paper/main.pdf' },
    });
    fireEvent.change(screen.getByTestId('latex-compliance-sections'), {
      target: { value: 'Introduction, Conclusion' },
    });
    fireEvent.change(screen.getByTestId('latex-compliance-metadata'), {
      target: { value: 'title' },
    });
    fireEvent.click(screen.getByTestId('latex-compliance-run'));

    await waitFor(() =>
      expect(mockedCheck).toHaveBeenCalledWith(
        '/ws',
        '/ws/paper/main.tex',
        '/ws/paper/main.pdf',
        expect.objectContaining({
          required_sections: ['Introduction', 'Conclusion'],
          required_metadata: ['title'],
          min_image_dpi: 150,
        }),
      ),
    );
    const result = screen.getByTestId('latex-compliance-result');
    expect(result).toHaveTextContent('存在不合规项');
    expect(result).toHaveTextContent('必需章节');
    expect(result).toHaveTextContent('LATEX-SECTION-REQUIRED');
  });

  it('shows backend errors', async () => {
    mockedCheck.mockRejectedValue(new Error('LaTeX 文件不在项目目录内'));

    render(<LatexCompliancePanel workspacePath="/ws" />);

    fireEvent.change(screen.getByTestId('latex-compliance-tex'), {
      target: { value: '../outside.tex' },
    });
    fireEvent.click(screen.getByTestId('latex-compliance-run'));

    await waitFor(() => expect(screen.getByText('LaTeX 文件不在项目目录内')).toBeTruthy());
  });

  it('loads a saved profile into the form', async () => {
    mockedList.mockResolvedValue({ profiles: [RECORD], warnings: [] });
    mockedLoad.mockResolvedValue(RECORD);

    render(<LatexCompliancePanel workspacePath="/ws" />);

    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'ieee-2026' })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId('latex-compliance-profile'), {
      target: { value: 'ieee-2026' },
    });

    await waitFor(() => expect(mockedLoad).toHaveBeenCalledWith('/ws', 'ieee-2026'));
    await waitFor(() =>
      expect(screen.getByTestId('latex-compliance-sections')).toHaveValue(
        'Introduction, Conclusion',
      ),
    );
    expect(screen.getByTestId('latex-compliance-dpi')).toHaveValue('300');
    expect(screen.getByTestId('latex-compliance-forbidden')).toHaveValue('write18');
  });
});
