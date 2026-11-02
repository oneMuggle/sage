import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { auditLatex, type LatexAuditResult } from '../../../shared/api/latexApi';
import { LatexAuditPanel } from '../LatexAuditPanel';

vi.mock('../../../shared/api/latexApi', () => ({
  auditLatex: vi.fn(),
}));

const mockedAudit = vi.mocked(auditLatex);

const RESULT: LatexAuditResult = {
  ok: false,
  source_path: 'paper/main.tex',
  issues: [
    {
      rule_id: 'LATEX-CITE-UNDEFINED',
      severity: 'error',
      category: 'citation',
      message: '引用 key 未在参考文献中找到: missing',
      fix_hint: '在 .bib 中添加该条目',
      anchor: { file: 'paper/main.tex', line: 8 },
    },
  ],
  summary: {
    count: 1,
    severity: { error: 1, warning: 0, info: 0 },
    categories: { citation: 1 },
  },
  required_sections: ['Introduction', 'Conclusion'],
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('LatexAuditPanel', () => {
  it('runs an audit and renders issues with anchors', async () => {
    mockedAudit.mockResolvedValue(RESULT);

    render(<LatexAuditPanel workspacePath="/ws" />);

    fireEvent.change(screen.getByTestId('latex-audit-path'), {
      target: { value: 'paper/main.tex' },
    });
    fireEvent.change(screen.getByTestId('latex-audit-sections'), {
      target: { value: 'Introduction, Conclusion' },
    });
    fireEvent.click(screen.getByTestId('latex-audit-run'));

    await waitFor(() => expect(screen.getByTestId('latex-audit-result')).toBeInTheDocument());
    expect(mockedAudit).toHaveBeenCalledWith('/ws', '/ws/paper/main.tex', [
      'Introduction',
      'Conclusion',
    ]);
    expect(screen.getByText('LATEX-CITE-UNDEFINED')).toBeInTheDocument();
    expect(screen.getByText(/paper\/main\.tex:8/)).toBeInTheDocument();
    expect(screen.getByText(/在 \.bib 中添加该条目/)).toBeInTheDocument();
  });

  it('reports an error without a bound workspace', async () => {
    render(<LatexAuditPanel workspacePath={null} />);

    fireEvent.change(screen.getByTestId('latex-audit-path'), {
      target: { value: 'paper/main.tex' },
    });
    fireEvent.click(screen.getByTestId('latex-audit-run'));

    await waitFor(() => expect(screen.getByText(/请先绑定工作区/)).toBeInTheDocument());
    expect(mockedAudit).not.toHaveBeenCalled();
  });
});
