/**
 * A4b — OfficeDeliveryDrawer: lint section, embedded preview,
 * and the accept/reject decision zone wired to taskCenterStore.
 *
 * Mocks at the desktopInvoke seam so the real officeApi flow is exercised.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn(),
}));

import { invoke } from '../../../shared/api/desktopInvoke';
import type {
  OfficeDocumentSummary,
  OfficeWordLintResult,
  OfficeWordReadResult,
  WordFormatSpec,
} from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useTaskCenterStore } from '../../task-center/taskCenterStore';
import { OfficeDeliveryDrawer } from '../OfficeDeliveryDrawer';

const invokeMock = invoke as unknown as ReturnType<typeof vi.fn>;

const SPEC: WordFormatSpec = { numbering: true };

function makeSummary(): OfficeDocumentSummary {
  return {
    id: 'doc-1',
    doc_type: 'word',
    original_filename: null,
    generated_filename: 'report.docx',
    status: 'generated',
    created_at: 0,
    updated_at: 0,
    metadata: { file_size_bytes: 42 },
    derived_from: null,
    archived_at: null,
  };
}

function makeReadResult(): OfficeWordReadResult {
  return {
    summary: makeSummary(),
    paragraphs: [{ style: 'Normal', text: 'hello delivery', level: 0 }],
    tables: [],
    images: 0,
  };
}

function makeLint(overrides: Partial<OfficeWordLintResult> = {}): OfficeWordLintResult {
  return {
    ok: true,
    issue_count: 0,
    error_count: 0,
    warning_count: 0,
    checked_rules: ['numbering'],
    issues: [],
    ...overrides,
  };
}

function seedEntry() {
  useTaskCenterStore.setState({ tasks: {}, delivery: null });
  useTaskCenterStore.getState().registerTask('office:generate', 'office', 'report.docx');
  useTaskCenterStore.getState().updateTask('office:generate', {
    status: 'awaiting_approval',
    deliveryRef: { workspacePath: '/ws', filePath: '/ws/report.docx', formatSpec: SPEC },
  });
}

function renderDrawer(formatSpec: WordFormatSpec | null = SPEC) {
  return render(
    <MemoryRouter initialEntries={['/chat']}>
      <I18nProvider>
        <OfficeDeliveryDrawer
          entryId="office:generate"
          workspacePath="/ws"
          filePath="/ws/report.docx"
          formatSpec={formatSpec}
          open
          onClose={() => {}}
        />
      </I18nProvider>
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}</div>;
}

describe('OfficeDeliveryDrawer (A4b)', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    seedEntry();
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'office_word_read') return makeReadResult();
      if (cmd === 'office_word_lint') return makeLint();
      return null;
    });
  });

  it('renders lint results with counts and issues', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'office_word_read') return makeReadResult();
      if (cmd === 'office_word_lint') {
        return makeLint({
          ok: false,
          issue_count: 2,
          error_count: 1,
          warning_count: 1,
          issues: [
            {
              rule_id: 'page/margins',
              severity: 'error',
              message: 'margin 1cm vs 2.54cm',
              fix_hint: '调页边距',
            },
            {
              rule_id: 'toc/presence',
              severity: 'warning',
              message: 'no toc field',
              fix_hint: '',
            },
          ],
        });
      }
      return null;
    });
    renderDrawer();

    await waitFor(() => expect(screen.getByTestId('lint-result')).toBeTruthy());
    expect(invokeMock).toHaveBeenCalledWith('office_word_lint', {
      workspacePath: '/ws',
      filePath: '/ws/report.docx',
      formatSpec: SPEC,
    });
    expect(screen.getByText('margin 1cm vs 2.54cm')).toBeTruthy();
    expect(screen.getByText('调页边距')).toBeTruthy();
    expect(screen.getByTestId('lint-issues')).toBeTruthy();
  });

  it('skips lint without calling the backend when no spec was given', async () => {
    renderDrawer(null);

    await waitFor(() => expect(screen.getByTestId('lint-skipped')).toBeTruthy());
    expect(invokeMock).not.toHaveBeenCalledWith(
      'office_word_lint',
      expect.objectContaining({}),
    );
    // Preview still loads; decisions still available.
    await waitFor(() => expect(screen.getByText('hello delivery')).toBeTruthy());
    expect(screen.getByTestId('decision-zone')).toBeTruthy();
  });

  it('lint failure shows retry; retry re-invokes the channel', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'office_word_read') return makeReadResult();
      if (cmd === 'office_word_lint') throw new Error('422 parse');
      return null;
    });
    renderDrawer();

    await waitFor(() => expect(screen.getByTestId('lint-retry')).toBeTruthy());
    expect(screen.getByTestId('decision-zone')).toBeTruthy();
    fireEvent.click(screen.getByTestId('lint-retry'));

    await waitFor(() =>
      expect(
        invokeMock.mock.calls.filter(([cmd]) => cmd === 'office_word_lint'),
      ).toHaveLength(2),
    );
  });

  it('embeds the document preview', async () => {
    renderDrawer();

    await waitFor(() => expect(screen.getByTestId('delivery-preview')).toBeTruthy());
    expect(screen.getByText('hello delivery')).toBeTruthy();
  });

  it('accept archives the entry and hides the decision zone', async () => {
    renderDrawer();
    await waitFor(() => expect(screen.getByTestId('decision-zone')).toBeTruthy());

    fireEvent.click(screen.getByTestId('decision-accept'));

    await waitFor(() => expect(screen.queryByTestId('decision-zone')).toBeNull());
    expect(useTaskCenterStore.getState().tasks['office:generate'].status).toBe('succeeded');
  });

  it('reject completes the entry as cancelled and jumps to the office page', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <I18nProvider>
          <Routes>
            <Route
              path="*"
              element={
                <>
                  <LocationProbe />
                  <OfficeDeliveryDrawer
                    entryId="office:generate"
                    workspacePath="/ws"
                    filePath="/ws/report.docx"
                    formatSpec={null}
                    open
                    onClose={() => {}}
                  />
                </>
              }
            />
          </Routes>
        </I18nProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId('decision-zone')).toBeTruthy());

    fireEvent.click(screen.getByTestId('decision-reject'));

    await waitFor(() => expect(screen.getByTestId('location-probe').textContent).toBe('/office'));
    expect(useTaskCenterStore.getState().tasks['office:generate'].status).toBe('cancelled');
  });

  it('renders nothing when closed or the entry is gone', () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <I18nProvider>
          <OfficeDeliveryDrawer
            entryId="office:generate"
            workspacePath="/ws"
            filePath="/ws/report.docx"
            formatSpec={null}
            open={false}
            onClose={() => {}}
          />
        </I18nProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByTestId('office-delivery-drawer')).toBeNull();
    unmount();

    useTaskCenterStore.getState().removeTask('office:generate');
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <I18nProvider>
          <OfficeDeliveryDrawer
            entryId="office:generate"
            workspacePath="/ws"
            filePath="/ws/report.docx"
            formatSpec={null}
            open
            onClose={() => {}}
          />
        </I18nProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByTestId('office-delivery-drawer')).toBeNull();
  });
});
