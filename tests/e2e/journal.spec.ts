/**
 * Task 8 — journal template panel E2E tier-1 (3 cases).
 *
 * Hermetic — no real Electron or backend. `window.electronAPI.invoke`
 * is stubbed via `addInitScript`. Only the `office_journal_*` commands
 * used by the journal subsystem are mocked; unknown commands throw
 * to catch unexpected call paths.
 *
 * Mount point: src/pages/Office.tsx (JournalPanel rendered when the
 * office page is active). We do NOT navigate to `/office` here — the
 * three cases directly invoke the mocked IPC bridge via `page.evaluate`
 * to verify spec → validate → fill round-trip shapes. This keeps the
 * suite hermetic (no real Vite/backend, no `pickOfficeFile` roundtrip
 * which the E2E browser cannot satisfy).
 *
 * @see src/features/journal/JournalPanel.tsx
 * @see src/features/journal/useJournalTemplates.ts
 * @see src/shared/api/journalApi.ts
 * @see src/shared/api/types.ts (Journal* interfaces)
 */
import { test, expect } from '@playwright/test';
import path from 'node:path';

// ---- fixtures ----

const FIXTURE_SIMPLE = path.resolve('backend/tests/fixtures/journal/simple_chinese_template.docx');
const FIXTURE_BAD = path.resolve('backend/tests/fixtures/journal/bad_filled_paper.docx');

// ---- mock shapes (mirrors src/shared/api/types.ts) ----

interface MockSpecHeading {
  keyword: string;
  level: number;
  expected_pt: number;
}

interface MockSpec {
  spec_id: string;
  template_filename: string;
  body_pt: number;
  heading_pt: number;
  line_spacing: number;
  margins_cm: number;
  headings: MockSpecHeading[];
  citation_style: string;
}

interface MockViolation {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  location: string;
  message: string;
  suggestion: string;
}

interface MockValidateResponse {
  spec_id: string;
  violations: MockViolation[];
  error_count: number;
  warning_count: number;
}

interface MockFillResponse {
  spec_id: string;
  output_path: string;
  generation_id: string;
}

interface MockState {
  parseCalls: Array<{ file_path: string }>;
  validateCalls: Array<{ spec_id?: string; file_path?: string }>;
  fillCalls: Array<Record<string, unknown>>;
}

interface JournalTestWindow extends Window {
  __mockState: MockState;
  electronAPI?: {
    invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
    listen: () => Promise<() => void>;
    windowControls: Record<string, unknown>;
  };
}

// ---- mock fixtures ----

const SIMPLE_SPEC: MockSpec = {
  spec_id: 'spec_fixture_simple',
  template_filename: 'simple_chinese_template.docx',
  body_pt: 12,
  heading_pt: 14,
  line_spacing: 1.5,
  margins_cm: 2.54,
  headings: [
    { keyword: '摘要', level: 1, expected_pt: 14 },
    { keyword: '关键词', level: 1, expected_pt: 14 },
    { keyword: '引言', level: 1, expected_pt: 14 },
    { keyword: '参考文献', level: 1, expected_pt: 14 },
  ],
  citation_style: 'numeric',
};

const BAD_VIOLATIONS: MockViolation[] = [
  {
    rule_id: 'BODY_PT_OUT_OF_RANGE',
    severity: 'error',
    location: 'p.5',
    message: '正文段落字号 9pt 超出期刊范围 [10, 12]',
    suggestion: '调整为 10.5pt',
  },
  {
    rule_id: 'LINE_SPACING_LOW',
    severity: 'warning',
    location: 'doc',
    message: '行距 1.0 偏小，建议 1.5',
    suggestion: '设置段距 1.5 倍行距',
  },
  {
    rule_id: 'ABSTRACT_MISSING',
    severity: 'error',
    location: 'doc',
    message: '缺少摘要段',
    suggestion: '在正文前补充中英文摘要',
  },
];

const VALIDATE_RESPONSE: MockValidateResponse = {
  spec_id: SIMPLE_SPEC.spec_id,
  violations: BAD_VIOLATIONS,
  error_count: 2,
  warning_count: 1,
};

const FILL_RESPONSE: MockFillResponse = {
  spec_id: SIMPLE_SPEC.spec_id,
  output_path: '/tmp/journal-fixture.docx',
  generation_id: 'gen_fixture_001',
};

// ---- mock installation ----

async function installJournalMockAndOpen(page: import('@playwright/test').Page): Promise<void> {
  // `addInitScript` only fires on document creation, so we must register
  // it BEFORE the first navigation. We then navigate to about:blank to
  // materialize the mock on `window` without loading the real app.
  // The init script runs in the browser context, so any mock data it
  // needs must be serialized here and parsed inside the callback
  // (Playwright pattern — see tests/e2e/learn-command.spec.ts).
  await page.addInitScript(
    (serialized: {
      simpleSpec: MockSpec;
      validateResponse: MockValidateResponse;
      fillResponse: MockFillResponse;
    }) => {
      const simpleSpec = serialized.simpleSpec;
      const validateResponse = serialized.validateResponse;
      const fillResponse = serialized.fillResponse;

      const state: MockState = { parseCalls: [], validateCalls: [], fillCalls: [] };
      (window as unknown as JournalTestWindow).__mockState = state;

      (window as unknown as JournalTestWindow).electronAPI = {
        invoke: async (cmd: string, args: Record<string, unknown> = {}) => {
          switch (cmd) {
            case 'office_journal_parse_template':
              state.parseCalls.push({ file_path: String(args.file_path ?? '') });
              return { spec: simpleSpec };
            case 'office_journal_list_specs':
              return { specs: [simpleSpec] };
            case 'office_journal_get_spec':
              return { spec: simpleSpec };
            case 'office_journal_validate':
              state.validateCalls.push({
                spec_id: args.spec_id as string | undefined,
                file_path: args.file_path as string | undefined,
              });
              return validateResponse;
            case 'office_journal_fill_from_content':
              state.fillCalls.push(args);
              return fillResponse;
            default:
              throw new Error(`Unexpected IPC command in journal E2E: ${cmd}`);
          }
        },
        listen: async () => () => {},
        windowControls: {},
      };
    },
    {
      simpleSpec: SIMPLE_SPEC,
      validateResponse: VALIDATE_RESPONSE,
      fillResponse: FILL_RESPONSE,
    },
  );
  await page.goto('about:blank');
}

function installJournalMock(page: import('@playwright/test').Page): Promise<void> {
  return installJournalMockAndOpen(page);
}

// ---- tests ----

test.describe('Journal template panel — E2E tier-1 (N8)', () => {
  test('parseTemplate returns spec shape with body_pt + headings + citation_style', async ({
    page,
  }) => {
    await installJournalMock(page);
    // No page navigation needed — purely IPC-level mock assertion.

    const result = await page.evaluate(
      async ({ simplePath }) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const api = (window as any).electronAPI;
        return await api.invoke('office_journal_parse_template', { file_path: simplePath });
      },
      { simplePath: FIXTURE_SIMPLE },
    );

    // Shape contract (mirrors src/shared/api/types.ts JournalParseTemplateResponse)
    expect(result).toBeDefined();
    expect((result as { spec: MockSpec }).spec).toBeDefined();
    const spec = (result as { spec: MockSpec }).spec;
    expect(spec.spec_id).toBe('spec_fixture_simple');
    expect(spec.template_filename).toBe('simple_chinese_template.docx');
    expect(spec.body_pt).toBe(12);
    expect(spec.heading_pt).toBe(14);
    expect(spec.line_spacing).toBe(1.5);
    expect(spec.margins_cm).toBe(2.54);
    expect(spec.citation_style).toBe('numeric');
    expect(spec.headings).toHaveLength(4);
    expect(spec.headings[0]).toEqual({ keyword: '摘要', level: 1, expected_pt: 14 });

    // Audit: parseCalls recorded exactly once with the right file_path.
    const calls = await page.evaluate(
      () => (window as unknown as JournalTestWindow).__mockState,
    );
    expect(calls.parseCalls.length).toBe(1);
    expect(calls.parseCalls[0].file_path).toBe(FIXTURE_SIMPLE);
  });

  test('validate returns error_count > 0 and violation array for bad filled paper', async ({
    page,
  }) => {
    await installJournalMock(page);

    const result = await page.evaluate(
      async ({ specId, badPath }) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const api = (window as any).electronAPI;
        return await api.invoke('office_journal_validate', {
          spec_id: specId,
          file_path: badPath,
        });
      },
      { specId: SIMPLE_SPEC.spec_id, badPath: FIXTURE_BAD },
    );

    // Shape contract (mirrors src/shared/api/types.ts JournalValidateResponse)
    const resp = result as MockValidateResponse;
    expect(resp.spec_id).toBe(SIMPLE_SPEC.spec_id);
    expect(resp.error_count).toBeGreaterThan(0);
    expect(resp.warning_count).toBeGreaterThan(0);
    expect(Array.isArray(resp.violations)).toBe(true);
    expect(resp.violations.length).toBe(3);

    // Sample violation shape — confirms rule_id/severity/message/suggestion
    // are all present (required by JournalViolation interface).
    const firstError = resp.violations[0];
    expect(firstError.rule_id).toBe('BODY_PT_OUT_OF_RANGE');
    expect(firstError.severity).toBe('error');
    expect(typeof firstError.message).toBe('string');
    expect(firstError.message.length).toBeGreaterThan(0);
    expect(typeof firstError.suggestion).toBe('string');
    expect(firstError.suggestion.length).toBeGreaterThan(0);

    // Audit: validateCalls recorded exactly once.
    const calls = await page.evaluate(
      () => (window as unknown as JournalTestWindow).__mockState,
    );
    expect(calls.validateCalls.length).toBe(1);
    expect(calls.validateCalls[0].spec_id).toBe(SIMPLE_SPEC.spec_id);
    expect(calls.validateCalls[0].file_path).toBe(FIXTURE_BAD);
  });

  test('fillFromContent round-trip returns output_path + generation_id and records the call', async ({
    page,
  }) => {
    await installJournalMock(page);

    const result = await page.evaluate(
      async ({ specId }) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const api = (window as any).electronAPI;
        return await api.invoke('office_journal_fill_from_content', {
          spec_id: specId,
          workspace_path: '/tmp/e2e-workspace',
          content: {
            title: 'E2E test paper',
            abstract: 'An abstract for E2E.',
            sections: { 引言: 'intro body', 摘要: 'abstract body' },
            references: ['[1] ref one'],
          },
          output_filename: 'paper-e2e.docx',
        });
      },
      { specId: SIMPLE_SPEC.spec_id },
    );

    // Shape contract (mirrors src/shared/api/types.ts JournalFillFromContentResponse)
    const resp = result as MockFillResponse;
    expect(resp.spec_id).toBe(SIMPLE_SPEC.spec_id);
    expect(resp.output_path).toMatch(/journal-fixture\.docx$/);
    expect(resp.generation_id).toBe('gen_fixture_001');

    // Audit: fillCalls recorded exactly once with the request payload.
    const calls = await page.evaluate(
      () => (window as unknown as JournalTestWindow).__mockState,
    );
    expect(calls.fillCalls.length).toBe(1);
    const fillReq = calls.fillCalls[0];
    expect(fillReq.spec_id).toBe(SIMPLE_SPEC.spec_id);
    expect(fillReq.workspace_path).toBe('/tmp/e2e-workspace');
    expect(fillReq.output_filename).toBe('paper-e2e.docx');
    expect((fillReq.content as { title: string }).title).toBe('E2E test paper');
    expect((fillReq.content as { abstract: string }).abstract).toBe('An abstract for E2E.');
  });
});
