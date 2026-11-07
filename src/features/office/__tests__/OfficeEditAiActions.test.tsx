/**
 * OfficeEditAiActions tests — P2 M6.
 *
 * Covers:
 *  - one button per instruction (rewrite / polish / expand / condense);
 *  - clicking a button sends the current text snapshot to aiApi.rewrite
 *    and hands the result back through onResult;
 *  - a failed request surfaces an in-component alert (role="alert") and
 *    never throws;
 *  - empty current text disables every button;
 *  - while a request is in flight all buttons stay disabled and the
 *    thinking label shows.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockRewrite = vi.fn();
vi.mock('../../../shared/api/aiApi', () => ({
  aiApi: { rewrite: (...args: unknown[]) => mockRewrite(...args) },
}));

import { I18nProvider } from '../../../shared/lib/i18n';
import { OfficeEditAiActions, type OfficeEditAiActionsProps } from '../OfficeEditAiActions';

const KINDS = ['rewrite', 'polish', 'expand', 'condense'] as const;

function renderActions(overrides: Partial<OfficeEditAiActionsProps> = {}) {
  return render(
    <I18nProvider defaultLocale="zh">
      <OfficeEditAiActions
        workspacePath="/tmp/ws"
        documentId="doc-1"
        getCurrentText={() => '现有文本'}
        onResult={vi.fn()}
        {...overrides}
      />
    </I18nProvider>,
  );
}

describe('OfficeEditAiActions', () => {
  beforeEach(() => {
    mockRewrite.mockReset();
  });

  it('renders one button per instruction', () => {
    renderActions();
    expect(screen.getByTestId('office-edit-ai-actions')).toBeInTheDocument();
    for (const kind of KINDS) {
      expect(screen.getByTestId(`office-edit-ai-${kind}`)).toBeInTheDocument();
    }
  });

  it('sends the current text to aiApi.rewrite and forwards the result', async () => {
    mockRewrite.mockResolvedValueOnce({ ok: true, result: '新文本', model: 'test-model' });
    const onResult = vi.fn();
    renderActions({ onResult });

    fireEvent.click(screen.getByTestId('office-edit-ai-polish'));

    await waitFor(() =>
      expect(mockRewrite).toHaveBeenCalledWith({
        workspacePath: '/tmp/ws',
        documentId: 'doc-1',
        text: '现有文本',
        instruction: 'polish',
      }),
    );
    await waitFor(() => expect(onResult).toHaveBeenCalledWith('新文本'));
  });

  it('shows an in-component alert when the request fails and does not throw', async () => {
    mockRewrite.mockRejectedValueOnce(new Error('boom'));
    const onResult = vi.fn();
    renderActions({ onResult });

    fireEvent.click(screen.getByTestId('office-edit-ai-expand'));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('请求失败：boom');
    expect(onResult).not.toHaveBeenCalled();
  });

  it('disables every button when the current text is empty', () => {
    renderActions({ getCurrentText: () => '' });
    for (const kind of KINDS) {
      expect(screen.getByTestId(`office-edit-ai-${kind}`)).toBeDisabled();
    }
  });

  it('disables every button and shows the thinking label while busy', async () => {
    let resolveRewrite: (value: unknown) => void = () => {};
    mockRewrite.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRewrite = resolve;
      }),
    );
    renderActions();

    fireEvent.click(screen.getByTestId('office-edit-ai-rewrite'));

    expect(await screen.findByText('生成中…')).toBeInTheDocument();
    for (const kind of KINDS) {
      expect(screen.getByTestId(`office-edit-ai-${kind}`)).toBeDisabled();
    }

    resolveRewrite({ ok: true, result: 'x', model: null });
    await waitFor(() => expect(screen.getByTestId('office-edit-ai-polish')).not.toBeDisabled());
    expect(screen.queryByText('生成中…')).not.toBeInTheDocument();
  });
});
