import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LatexPreview } from '../LatexPreview';
import type { LatexStructured } from '../latexTypes';

const DATA: LatexStructured = {
  source_path: 'paper/main.tex',
  metadata: {
    document_class: 'article',
    title: 'Demo Paper',
    authors: ['Alice', 'Bob'],
  },
  blocks: [
    { type: 'heading', level: 1, text: 'Introduction' },
    {
      type: 'paragraph',
      text: 'Inline math $x^2$ and a citation [knuth84].',
    },
    { type: 'equation', latex: 'E = mc^2', display: true },
    {
      type: 'figure',
      src: 'data:image/png;base64,AAAA',
      caption: 'Architecture',
      label: 'fig:arch',
    },
    {
      type: 'table',
      headers: ['A', 'B'],
      rows: [['1', '2']],
      caption: 'Results',
    },
    {
      type: 'bibliography',
      entries: [{ key: 'knuth84', text: 'D. Knuth. The TeXbook. 1984.' }],
    },
  ],
  warnings: [
    {
      code: 'unknown_command',
      message: '未识别命令 \\foo',
      anchor: { file: 'paper/main.tex', line: 7 },
    },
  ],
};

describe('LatexPreview', () => {
  it('renders metadata, headings, math, figure, table and bibliography', () => {
    render(<LatexPreview data={DATA} source="\\documentclass{article}" />);

    expect(screen.getByTestId('latex-preview')).toBeInTheDocument();
    expect(screen.getByText('Demo Paper')).toBeInTheDocument();
    expect(screen.getByText('Alice · Bob')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Introduction' })).toBeInTheDocument();
    expect(document.querySelector('.katex')).not.toBeNull();
    expect(screen.getByAltText('Architecture')).toBeInTheDocument();
    expect(screen.getByText('Results')).toBeInTheDocument();
    expect(screen.getByText('D. Knuth. The TeXbook. 1984.')).toBeInTheDocument();
  });

  it('renders parser warnings with anchor', () => {
    render(<LatexPreview data={DATA} />);

    expect(screen.getByTestId('latex-warnings')).toBeInTheDocument();
    expect(screen.getByText(/未识别命令/)).toBeInTheDocument();
    expect(screen.getByText(/paper\/main\.tex:7/)).toBeInTheDocument();
  });

  it('toggles between preview and raw source', () => {
    render(<LatexPreview data={DATA} source="\\documentclass{article}" />);

    fireEvent.click(screen.getByTestId('latex-source-toggle'));
    expect(screen.getByTestId('latex-source')).toHaveTextContent('\\documentclass{article}');

    fireEvent.click(screen.getByTestId('latex-source-toggle'));
    expect(screen.queryByTestId('latex-source')).not.toBeInTheDocument();
  });
});
