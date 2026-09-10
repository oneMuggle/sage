import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { JournalSpecCard } from '../components/JournalSpecCard';

const stubSpec = {
  spec_id: 'spec_001',
  template_filename: 'cell-press.docx',
  body_pt: 10.5,
  heading_pt: 13,
  line_spacing: 1.15,
  margins_cm: 2.0,
  citation_style: 'cell-numeric',
  headings: [
    { keyword: 'Introduction', level: 1, expected_pt: 13 },
    { keyword: 'Results', level: 1, expected_pt: 13 },
    { keyword: 'Methods', level: 2, expected_pt: 11 },
  ],
};

describe('JournalSpecCard', () => {
  it('shows empty-state when no spec', () => {
    render(<JournalSpecCard spec={null} />);
    expect(screen.getByText(/尚未选择模板/)).toBeTruthy();
    expect(screen.getByText(/选择模板/)).toBeTruthy();
  });

  it('renders all spec fields when given a spec', () => {
    render(<JournalSpecCard spec={stubSpec} />);
    expect(screen.getByText('cell-press.docx')).toBeTruthy();
    expect(screen.getByText('10.5 pt')).toBeTruthy();
    expect(screen.getByText('13 pt')).toBeTruthy();
    expect(screen.getByText('1.15 倍')).toBeTruthy();
    expect(screen.getByText('2 cm')).toBeTruthy();
    expect(screen.getByText('cell-numeric')).toBeTruthy();
  });

  it('renders the headings list with level + pt metadata', () => {
    render(<JournalSpecCard spec={stubSpec} />);
    expect(screen.getByText(/章节 \(3\)/)).toBeTruthy();
    expect(screen.getByText('Introduction')).toBeTruthy();
    expect(screen.getByText('Results')).toBeTruthy();
    expect(screen.getByText('Methods')).toBeTruthy();
    // Two headings share L1·13pt (Introduction + Results) → expect multiple matches
    expect(screen.getAllByText(/\(L1 · 13pt\)/)).toHaveLength(2);
    expect(screen.getByText(/\(L2 · 11pt\)/)).toBeTruthy();
  });

  it('omits the headings section when headings array is empty', () => {
    render(<JournalSpecCard spec={{ ...stubSpec, headings: [] }} />);
    expect(screen.queryByText(/章节 \(0\)/)).toBeNull();
  });
});
