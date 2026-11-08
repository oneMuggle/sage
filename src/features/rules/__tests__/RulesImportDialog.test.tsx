// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ImportCandidate } from '../../../shared/api/rulesApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { RulesImportDialog } from '../RulesImportDialog';

const { previewImport, applyImport } = vi.hoisted(() => ({
  previewImport: vi.fn(),
  applyImport: vi.fn(),
}));

vi.mock('../../../shared/api/rulesApi', () => ({
  rulesApi: { previewImport, applyImport },
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

const ENVELOPE = { format: 'sage.rules', version: 1, layers: {} };

const CONSTRAINT_CANDIDATE: ImportCandidate = {
  id: 'import-constraint-0',
  kind: 'constraint',
  status: 'new',
  content: '统一使用 ruff',
  priority: 5,
  enabled: true,
};

const PLAYBOOK_CANDIDATE: ImportCandidate = {
  id: 'import-playbook-0',
  kind: 'playbook',
  status: 'new',
  content: '规程正文',
  priority: 5,
  enabled: true,
};

const GLOBAL_CANDIDATE: ImportCandidate = {
  id: 'import-global-0',
  kind: 'global',
  status: 'new',
  content: '# global rules',
  priority: 5,
  enabled: true,
};

const APPLY_RESULT = {
  applied: 1,
  failed: 0,
  results: [{ id: 'import-constraint-0', status: 'applied', message: 'ok' }],
};

function makeFile(content: unknown = ENVELOPE): File {
  return new File([JSON.stringify(content)], 'rules.sagerules.json', {
    type: 'application/json',
  });
}

function renderDialog() {
  const onOpenChange = vi.fn();
  const onApplied = vi.fn();
  render(
    <I18nProvider defaultLocale="zh">
      <RulesImportDialog open onOpenChange={onOpenChange} projectId="p1" onApplied={onApplied} />
    </I18nProvider>,
  );
  return { onOpenChange, onApplied };
}

function upload(file: File = makeFile()) {
  fireEvent.change(screen.getByTestId('rules-import-file'), {
    target: { files: [file] },
  });
}

describe('RulesImportDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a parse error when preview fails', async () => {
    previewImport.mockRejectedValue(new Error('bad envelope'));
    renderDialog();

    upload();

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('bad envelope'));
  });

  it('applies the auto-selected candidates with overwrite off by default', async () => {
    previewImport.mockResolvedValue({ candidates: [CONSTRAINT_CANDIDATE] });
    applyImport.mockResolvedValue(APPLY_RESULT);
    const { onApplied, onOpenChange } = renderDialog();

    upload();
    await waitFor(() =>
      expect(screen.getByTestId('rules-import-candidate-import-constraint-0')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('rules-import-apply'));

    await waitFor(() => expect(applyImport).toHaveBeenCalledTimes(1));
    const [envelope, projectId, selected, overwrite] = applyImport.mock.calls[0];
    expect(envelope).toEqual(ENVELOPE);
    expect(projectId).toBe('p1');
    expect(selected).toEqual(['import-constraint-0']);
    expect(overwrite).toBe(false);
    expect(onApplied).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('never selects or applies playbook candidates', async () => {
    previewImport.mockResolvedValue({
      candidates: [CONSTRAINT_CANDIDATE, PLAYBOOK_CANDIDATE],
    });
    applyImport.mockResolvedValue(APPLY_RESULT);
    renderDialog();

    upload();
    await waitFor(() => expect(screen.getByTestId('rules-import-candidates')).toBeInTheDocument());

    expect(screen.queryByTestId('rules-import-playbook-deferred')).not.toBeNull();
    expect(screen.queryByTestId('rules-import-candidate-import-playbook-0')).toBeNull();
    fireEvent.click(screen.getByTestId('rules-import-apply'));

    await waitFor(() => expect(applyImport).toHaveBeenCalledTimes(1));
    const [, , selected] = applyImport.mock.calls[0];
    expect(selected).toEqual(['import-constraint-0']);
  });

  it('disables apply until global rules are acknowledged', async () => {
    previewImport.mockResolvedValue({ candidates: [GLOBAL_CANDIDATE] });
    applyImport.mockResolvedValue(APPLY_RESULT);
    renderDialog();

    upload();
    await waitFor(() => expect(screen.getByTestId('rules-import-global-ack')).toBeInTheDocument());

    const applyButton = screen.getByTestId('rules-import-apply');
    expect(applyButton).toBeDisabled();

    const ack = within(screen.getByTestId('rules-import-global-ack')).getByRole('checkbox');
    fireEvent.click(ack);
    expect(applyButton).toBeEnabled();

    fireEvent.click(applyButton);
    await waitFor(() => expect(applyImport).toHaveBeenCalledTimes(1));
    const [, , selected] = applyImport.mock.calls[0];
    expect(selected).toEqual(['import-global-0']);
  });
});
