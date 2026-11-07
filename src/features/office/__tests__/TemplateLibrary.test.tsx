import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { TemplateLibrary } from '../TemplateLibrary';

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: { listTemplates: vi.fn() },
}));

const mockedListTemplates = vi.mocked(officeApi.listTemplates);

const BUILTIN = {
  id: 'weekly_report',
  name: '周报',
  description: '内置周报模板',
  doc_type: 'word' as const,
  placeholders: [],
  source: 'builtin' as const,
};

const WORKSPACE = {
  id: 'my-doc',
  name: '我的模板',
  doc_type: 'word' as const,
  placeholders: [],
  source: 'workspace' as const,
  filename: 'my-template.docx',
};

function renderLibrary(onSelect = vi.fn()) {
  render(
    <I18nProvider defaultLocale="zh">
      <TemplateLibrary workspacePath="/ws" selectedId="weekly_report" onSelect={onSelect} />
    </I18nProvider>,
  );
  return onSelect;
}

describe('TemplateLibrary', () => {
  beforeEach(() => {
    mockedListTemplates.mockReset();
    mockedListTemplates.mockResolvedValue({ templates: [BUILTIN, WORKSPACE] });
  });

  it('renders builtin and workspace templates with source badges', async () => {
    renderLibrary();

    const builtin = await screen.findByTestId('office-template-library-item-weekly_report');
    expect(builtin).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('office-template-library-item-my-doc')).toBeInTheDocument();
    expect(screen.getByTestId('office-template-library-source-weekly_report').textContent).toBe(
      '内置',
    );
    expect(screen.getByTestId('office-template-library-source-my-doc').textContent).toBe('工作区');
  });

  it('selects a template through onSelect', async () => {
    const onSelect = renderLibrary();
    fireEvent.click(await screen.findByTestId('office-template-library-item-my-doc'));
    expect(onSelect).toHaveBeenCalledWith(WORKSPACE);
  });

  it('shows the error state and reloads on retry', async () => {
    mockedListTemplates.mockRejectedValueOnce(new Error('boom'));
    renderLibrary();

    await screen.findByTestId('office-template-library-error');
    fireEvent.click(screen.getByTestId('office-template-library-retry'));

    await waitFor(() =>
      expect(screen.getByTestId('office-template-library-item-weekly_report')).toBeInTheDocument(),
    );
    expect(mockedListTemplates).toHaveBeenCalledTimes(2);
  });
});
