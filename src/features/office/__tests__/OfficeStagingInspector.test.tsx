import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  formatOfficeStagingJson,
  formatOfficeStagingMarkdown,
  OfficeStagingInspector,
} from '../OfficeStagingInspector';

vi.mock('../../../shared/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('Office staging inspection UI', () => {
  it('is explicit, read-only, and discards late workspace results', async () => {
    let resolve!: (value: unknown) => void;
    const previewStaging = vi.fn(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    vi.stubGlobal('electronAPI', { office: { previewStaging } });
    const view = render(<OfficeStagingInspector workspacePath="/first" />);
    expect(previewStaging).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button'));
    expect(previewStaging).toHaveBeenCalledWith('/first');
    view.rerender(<OfficeStagingInspector workspacePath="/second" />);
    await act(async () => {
      resolve({
        readOnly: true,
        truncated: false,
        items: [{ docType: 'word', documentId: 'OLD', status: 'review' }],
      });
    });
    expect(screen.queryByText('word/OLD')).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  it('handles older desktop builds without triggering any other IPC', async () => {
    vi.stubGlobal('electronAPI', { office: {} });
    render(<OfficeStagingInspector workspacePath="/workspace" />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button'));
    });
    expect(screen.getByRole('alert').textContent).toBe('office.staging.unavailable');
  });

  it('exports staging report as Markdown and JSON and copies via buttons', async () => {
    expect(formatOfficeStagingMarkdown('/ws', null)).toContain('_尚未执行暂存区检查_');
    expect(
      formatOfficeStagingMarkdown('/ws', { readOnly: true, truncated: false, items: [] }),
    ).toContain('_暂无暂存文档_');
    const sampleReport = {
      readOnly: true as const,
      truncated: true,
      items: [{ docType: 'word' as const, documentId: 'DOC-1', status: 'review' as const }],
    };
    const md = formatOfficeStagingMarkdown('/ws', sampleReport);
    expect(md).toContain('`word/DOC-1` — review');
    const parsed = JSON.parse(formatOfficeStagingJson('/ws', sampleReport));
    expect(parsed.workspacePath).toBe('/ws');
    expect(parsed.report.items).toHaveLength(1);

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const previewStaging = vi.fn().mockResolvedValue(sampleReport);
    vi.stubGlobal('electronAPI', { office: { previewStaging } });
    render(<OfficeStagingInspector workspacePath="/ws" />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button'));
    });
    fireEvent.click(screen.getByTestId('office-staging-copy-md'));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('word/DOC-1'));
    fireEvent.click(screen.getByTestId('office-staging-copy-json'));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('"documentId": "DOC-1"'));
  });
});
