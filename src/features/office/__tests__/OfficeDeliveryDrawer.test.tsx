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

/**
 * P0-2（2026-10-01）：接上此前零调用的 POST /office/word/repair。
 * 接线前抽屉只报问题不给修法 —— 用户看到 lint 失败后无路可走。
 */
describe('OfficeDeliveryDrawer 自动修复（P0-2）', () => {
  const FAILING_LINT = makeLint({
    ok: false,
    issue_count: 1,
    error_count: 1,
    warning_count: 0,
    issues: [
      { rule_id: 'page/margins', severity: 'error', message: 'margin 1cm vs 2.54cm', fix_hint: '调页边距' },
    ],
  });

  function makeRepair(remainingOk: boolean) {
    return {
      ok: true,
      repaired_rules: ['page/margins'],
      output_path: '/ws/report-repaired.docx',
      overwrite: false,
      remaining: makeLint({
        ok: remainingOk,
        issue_count: remainingOk ? 0 : 1,
        error_count: remainingOk ? 0 : 1,
        warning_count: 0,
        issues: remainingOk
          ? []
          : [
              {
                rule_id: 'citation/coverage',
                severity: 'error',
                message: 'citation missing',
                fix_hint: '补引用',
              },
            ],
      }),
    };
  }

  beforeEach(() => {
    invokeMock.mockReset();
    seedEntry();
  });

  it('lint 通过时不显示修复入口（没有可修的东西）', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'office_word_read') return makeReadResult();
      if (cmd === 'office_word_lint') return makeLint();
      return null;
    });
    renderDrawer();
    await waitFor(() => expect(screen.getByTestId('lint-result')).toBeTruthy());
    expect(screen.queryByTestId('lint-repair-button')).toBeNull();
  });

  it('点击修复走 repair 通道，且默认不覆盖原稿', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'office_word_read') return makeReadResult();
      if (cmd === 'office_word_lint') return FAILING_LINT;
      if (cmd === 'office_word_repair') return makeRepair(true);
      return null;
    });
    renderDrawer();
    await waitFor(() => expect(screen.getByTestId('lint-repair-button')).toBeTruthy());

    fireEvent.click(screen.getByTestId('lint-repair-button'));

    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('office_word_repair', {
        workspacePath: '/ws',
        filePath: '/ws/report.docx',
        formatSpec: SPEC,
        overwrite: false,
      }),
    );
    // 修复版另存，原稿不动（不可逆操作须显式确认）
    const report = await screen.findByTestId('lint-repair-report');
    expect(report.textContent).toContain('已修复 1 条规则');
    expect(report.textContent).toContain('report-repaired.docx');
  }, 20000);

  it('复检后仍有语义类问题则如实提示剩余数量', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'office_word_read') return makeReadResult();
      if (cmd === 'office_word_lint') return FAILING_LINT;
      if (cmd === 'office_word_repair') return makeRepair(false);
      return null;
    });
    renderDrawer();
    await waitFor(() => expect(screen.getByTestId('lint-repair-button')).toBeTruthy());
    fireEvent.click(screen.getByTestId('lint-repair-button'));

    const remaining = await screen.findByTestId('lint-repair-remaining');
    expect(remaining.textContent).toContain('1 条');
  }, 20000);

  it('修复后以复检结果刷新问题列表', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'office_word_read') return makeReadResult();
      if (cmd === 'office_word_lint') return FAILING_LINT;
      if (cmd === 'office_word_repair') return makeRepair(false);
      return null;
    });
    renderDrawer();
    await waitFor(() => expect(screen.getByTestId('lint-repair-button')).toBeTruthy());
    expect(screen.getByText('margin 1cm vs 2.54cm')).toBeTruthy();

    fireEvent.click(screen.getByTestId('lint-repair-button'));

    // 复检结果替换原问题列表：旧问题消失，新问题出现
    await waitFor(() => expect(screen.queryByText('margin 1cm vs 2.54cm')).toBeNull());
    expect(screen.getByText('citation missing')).toBeTruthy();
  }, 20000);

  it('修复失败时保留问题列表并给出失败提示', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'office_word_read') return makeReadResult();
      if (cmd === 'office_word_lint') return FAILING_LINT;
      if (cmd === 'office_word_repair') throw new Error('repair boom');
      return null;
    });
    renderDrawer();
    await waitFor(() => expect(screen.getByTestId('lint-repair-button')).toBeTruthy());
    fireEvent.click(screen.getByTestId('lint-repair-button'));

    expect(await screen.findByTestId('lint-repair-failed')).toBeTruthy();
    // 关键：失败不得抹掉已有问题列表
    expect(screen.getByText('margin 1cm vs 2.54cm')).toBeTruthy();
    expect(screen.getByTestId('lint-repair-button')).toBeTruthy();
  }, 20000);
});
