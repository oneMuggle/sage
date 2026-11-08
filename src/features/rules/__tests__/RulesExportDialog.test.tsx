// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { RulesExportDialog } from '../RulesExportDialog';

const { exportRules } = vi.hoisted(() => ({ exportRules: vi.fn() }));

vi.mock('../../../shared/api/rulesApi', () => ({
  rulesApi: { exportRules },
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

function renderDialog() {
  const onOpenChange = vi.fn();
  render(
    <I18nProvider defaultLocale="zh">
      <RulesExportDialog open onOpenChange={onOpenChange} projectId="p1" projectName="演示项目" />
    </I18nProvider>,
  );
  return { onOpenChange };
}

describe('RulesExportDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: vi.fn(() => 'blob:mock'),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  it('calls the export API with the default scope and closes on success', async () => {
    exportRules.mockResolvedValue({
      format: 'sage.rules',
      filename: 'demo.sagerules.json',
      content: '{"format":"sage.rules"}',
    });
    const { onOpenChange } = renderDialog();

    fireEvent.click(screen.getByTestId('rules-export-confirm'));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    const [projectId, options] = exportRules.mock.calls[0];
    expect(projectId).toBe('p1');
    expect(options).toMatchObject({
      format: 'json',
      includeConstraints: true,
      includeDocs: true,
      includeGlobal: false,
      includePlaybook: true,
    });
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it('sends the chosen format and scope', async () => {
    exportRules.mockResolvedValue({
      format: 'markdown',
      filename: 'demo.sagerules.md',
      content: '# rules',
    });
    renderDialog();

    fireEvent.click(screen.getByTestId('rules-export-format-md'));
    fireEvent.click(screen.getByTestId('rules-export-scope-docs'));
    fireEvent.click(screen.getByTestId('rules-export-scope-global'));
    fireEvent.click(screen.getByTestId('rules-export-confirm'));

    await waitFor(() => expect(exportRules).toHaveBeenCalledTimes(1));
    const [, options] = exportRules.mock.calls[0];
    expect(options).toMatchObject({ format: 'md', includeDocs: false, includeGlobal: true });
  });

  it('shows the global warning only after global rules are checked', () => {
    renderDialog();

    expect(screen.queryByTestId('rules-export-global-warning')).toBeNull();
    fireEvent.click(screen.getByTestId('rules-export-scope-global'));
    expect(screen.getByTestId('rules-export-global-warning')).toBeInTheDocument();
  });

  it('surfaces a failure toast when export rejects', async () => {
    exportRules.mockRejectedValue(new Error('boom'));
    renderDialog();

    fireEvent.click(screen.getByTestId('rules-export-confirm'));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });
});
