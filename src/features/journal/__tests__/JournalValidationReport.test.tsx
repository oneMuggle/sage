import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { JournalViolation } from '../../../shared/api/types';
import { JournalValidationReport } from '../components/JournalValidationReport';

const errors: JournalViolation[] = [
  {
    rule_id: 'BODY_PT_OUT_OF_RANGE',
    severity: 'error',
    location: 'p.5',
    message: '正文段落字号 9pt 超出期刊范围 [10, 12]',
    suggestion: '调整为 10.5pt',
  },
];
const warnings: JournalViolation[] = [
  {
    rule_id: 'HEADING_H1_MISSING',
    severity: 'warning',
    location: 'doc',
    message: '检测到 0 个一级标题，期刊模板至少 3 个',
    suggestion: '',
  },
];
const info: JournalViolation[] = [
  {
    rule_id: 'CITATION_STYLE_OK',
    severity: 'info',
    location: 'doc',
    message: '引用风格与模板一致',
    suggestion: '',
  },
];

describe('JournalValidationReport', () => {
  it('shows empty-state when there are no violations', () => {
    render(<JournalValidationReport violations={[]} errorCount={0} warningCount={0} />);
    expect(screen.getByText('无违规项')).toBeTruthy();
  });

  it('renders the summary counts', () => {
    render(
      <JournalValidationReport
        violations={[...errors, ...warnings, ...info]}
        errorCount={1}
        warningCount={1}
      />,
    );
    expect(screen.getByText(/1 错误 · 1 警告/)).toBeTruthy();
  });

  it('renders each violation with rule_id + location + message', () => {
    render(
      <JournalValidationReport
        violations={[...errors, ...warnings]}
        errorCount={1}
        warningCount={1}
      />,
    );
    expect(screen.getByText(/\[错误\] BODY_PT_OUT_OF_RANGE · p\.5/)).toBeTruthy();
    expect(
      screen.getByText('正文段落字号 9pt 超出期刊范围 [10, 12]'),
    ).toBeTruthy();
    expect(screen.getByText('建议: 调整为 10.5pt')).toBeTruthy();

    expect(screen.getByText(/\[警告\] HEADING_H1_MISSING · doc/)).toBeTruthy();
    expect(screen.getByText('检测到 0 个一级标题，期刊模板至少 3 个')).toBeTruthy();
  });

  it('renders info-severity violations with their label', () => {
    render(
      <JournalValidationReport violations={info} errorCount={0} warningCount={0} />,
    );
    expect(screen.getByText(/\[提示\] CITATION_STYLE_OK · doc/)).toBeTruthy();
  });
});
