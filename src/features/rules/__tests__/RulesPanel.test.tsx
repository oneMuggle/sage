// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { RuleEntry } from '../../../shared/api/rulesApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { RulesPanel } from '../RulesPanel';

// jsdom 不实现 ResizeObserver，但 @headlessui Dialog 内部使用它
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

const { list, effective } = vi.hoisted(() => ({ list: vi.fn(), effective: vi.fn() }));

vi.mock('../../../shared/api/rulesApi', () => ({
  rulesApi: { list, effective },
}));

function rule(overrides: Partial<RuleEntry> & Pick<RuleEntry, 'id' | 'layer'>): RuleEntry {
  return {
    sourceLabel: '项目规则',
    scope: '全局',
    category: 'coding_style',
    content: '使用双引号',
    enabled: true,
    editable: 'full',
    priority: 5,
    trigger: null,
    updatedAt: null,
    origin: null,
    ...overrides,
  };
}

const RULES: RuleEntry[] = [
  rule({ id: 'global:#0', layer: 'global', sourceLabel: '全局规则', content: '回答用中文' }),
  rule({
    id: 'doc:SAGE.md#0',
    layer: 'doc',
    sourceLabel: '项目总纲 SAGE.md',
    content: '提交前跑 pytest',
  }),
  rule({ id: 'constraint:1', layer: 'constraint', content: '使用双引号' }),
  rule({ id: 'constraint:2', layer: 'constraint', content: '使用 ruff', enabled: false }),
  rule({
    id: 'playbook:s1:0',
    layer: 'playbook',
    sourceLabel: '规程 · 需求分析',
    editable: 'partial',
    content: '需求文档包含验收标准',
  }),
];

const CONFLICTS = [
  { a: 'constraint:1', b: 'doc:SAGE.md#0', category: 'coding_style', triggers: [null, null] },
];

function renderPanel(onOpenSource?: (entry: RuleEntry) => void) {
  return render(
    <I18nProvider defaultLocale="zh">
      <RulesPanel projectId="p-1" onOpenSource={onOpenSource} />
    </I18nProvider>,
  );
}

beforeEach(() => {
  list.mockReset();
  effective.mockReset();
  list.mockResolvedValue(RULES);
  effective.mockResolvedValue({
    entries: RULES.filter((entry) => entry.enabled),
    conflicts: CONFLICTS,
  });
});

describe('RulesPanel', () => {
  it('renders grouped rules, the health badge and conflict hints', async () => {
    renderPanel();

    expect(await screen.findByTestId('rules-group-global')).toBeInTheDocument();
    for (const layer of ['doc', 'constraint', 'playbook']) {
      expect(screen.getByTestId(`rules-group-${layer}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId('rules-count-enabled').textContent).toContain('4');
    expect(screen.getByTestId('rules-count-conflicts').textContent).toContain('1');
    expect(screen.getByTestId('rule-conflict-constraint:1')).toBeInTheDocument();
    expect(screen.getByTestId('rule-lock-playbook:s1:0')).toBeInTheDocument();
    expect(screen.queryByTestId('rule-lock-constraint:1')).toBeNull();
  });

  it('filters by layer chip', async () => {
    renderPanel();
    await screen.findByTestId('rules-group-global');

    fireEvent.click(screen.getByTestId('rules-filter-playbook'));

    expect(screen.getByTestId('rules-group-playbook')).toBeInTheDocument();
    expect(screen.queryByTestId('rules-group-global')).toBeNull();
    expect(screen.queryByTestId('rules-group-constraint')).toBeNull();
  });

  it('filters by search text and shows the filtered empty state', async () => {
    renderPanel();
    await screen.findByTestId('rules-group-global');

    fireEvent.change(screen.getByTestId('rules-search'), { target: { value: 'pytest' } });
    expect(screen.getByTestId('rule-row-doc:SAGE.md#0')).toBeInTheDocument();
    expect(screen.queryByTestId('rule-row-constraint:1')).toBeNull();

    fireEvent.change(screen.getByTestId('rules-search'), { target: { value: '不存在的规则' } });
    expect(screen.getByTestId('rules-empty-filtered')).toBeInTheDocument();
  });

  it('opens the effective drawer with only enabled rules in injection order', async () => {
    renderPanel();
    await screen.findByTestId('rules-group-global');

    expect(screen.getByTestId('rule-row-constraint:2')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('rules-effective-open'));

    const rows = await screen.findAllByTestId(/^rules-effective-row-/);
    expect(rows.map((row) => row.getAttribute('data-testid'))).toEqual([
      'rules-effective-row-global:#0',
      'rules-effective-row-doc:SAGE.md#0',
      'rules-effective-row-constraint:1',
      'rules-effective-row-playbook:s1:0',
    ]);
    expect(screen.queryByTestId('rules-effective-row-constraint:2')).toBeNull();
    expect(screen.getByTestId('rules-effective-conflict-constraint:1')).toBeInTheDocument();
  });

  it('renders the empty state when the project has no rules', async () => {
    list.mockResolvedValue([]);
    effective.mockResolvedValue({ entries: [], conflicts: [] });

    renderPanel();

    expect(await screen.findByTestId('rules-empty')).toBeInTheDocument();
  });

  it('surfaces load failures and retries', async () => {
    list.mockRejectedValueOnce(new Error('backend down'));

    renderPanel();

    expect(await screen.findByTestId('rules-error')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('rules-retry'));
    await waitFor(() => expect(screen.getByTestId('rules-group-global')).toBeInTheDocument());
  });

  it('forwards playbook rows to the source handler', async () => {
    const onOpenSource = vi.fn();
    renderPanel(onOpenSource);
    await screen.findByTestId('rules-group-playbook');

    fireEvent.click(screen.getByTestId('rule-source-playbook:s1:0'));

    expect(onOpenSource).toHaveBeenCalledWith(expect.objectContaining({ id: 'playbook:s1:0' }));
  });
});
