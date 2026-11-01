import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { OfficeWordReadResult } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { WordPreview } from '../OfficeStructuredPreviews';

const DATA = {
  summary: {
    id: 'doc-1',
    doc_type: 'word',
    original_filename: 'doc.docx',
    generated_filename: 'doc.docx',
    status: 'parsed',
    created_at: 0,
    updated_at: 0,
    metadata: { file_size_bytes: 100 },
    derived_from: null,
    archived_at: null,
    workspace_path: '/ws',
  },
  paragraphs: [
    { text: '第一段', style: 'Normal', level: 0 },
    { text: '第二段', style: 'Normal', level: 0 },
    { text: '1 引言', style: 'Heading 1', level: 1 },
  ],
  tables: [],
  images: 0,
} as unknown as OfficeWordReadResult;

afterEach(() => {
  vi.restoreAllMocks();
});

describe('WordPreview anchor highlight (M2c)', () => {
  it('renders paragraph anchors without highlighting by default', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <WordPreview data={DATA} />
      </I18nProvider>,
    );

    expect(screen.getByTestId('office-word-preview')).toBeInTheDocument();
    expect(screen.getByText('第一段')).toHaveAttribute('data-paragraph-index', '0');
    expect(screen.getByText('第一段').className).not.toContain('ring-primary');
  });

  it('highlights and scrolls to the anchored paragraph', () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;

    render(
      <I18nProvider defaultLocale="zh">
        <WordPreview data={DATA} highlightParagraphIndex={2} />
      </I18nProvider>,
    );

    const target = screen.getByText('1 引言');
    expect(target).toHaveAttribute('data-paragraph-index', '2');
    expect(target.className).toContain('ring-primary');
    expect(scrollIntoView).toHaveBeenCalled();
    expect(screen.getByText('第一段').className).not.toContain('ring-primary');
  });

  it('expands the render window when the anchor is beyond the cap', async () => {
    const paragraphs = Array.from({ length: 320 }, (_, index) => ({
      text: `段${index}`,
      style: 'Normal',
      level: 0,
    }));
    const big = { ...DATA, paragraphs } as unknown as OfficeWordReadResult;

    render(
      <I18nProvider defaultLocale="zh">
        <WordPreview data={big} highlightParagraphIndex={305} />
      </I18nProvider>,
    );

    await waitFor(() => expect(screen.getByText('段305')).toBeInTheDocument());
    expect(screen.getByText('段305').className).toContain('ring-primary');
  });
});
