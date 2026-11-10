// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
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

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

const { list, effective, create, update, remove, raw, previewPatch, applyPatch, confirmDialog } =
  vi.hoisted(() => ({
    list: vi.fn(),
    effective: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    raw: vi.fn(),
    previewPatch: vi.fn(),
    applyPatch: vi.fn(),
    confirmDialog: vi.fn(),
  }));

vi.mock('../../../shared/api/rulesApi', () => ({
  rulesApi: { list, effective, create, update, remove, raw, previewPatch, applyPatch },
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: (...args: unknown[]) => confirmDialog(...args),
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

const CONSTRAINT_ENTRY: RuleEntry = {
  id: 'constraint:1',
  layer: 'constraint',
  sourceLabel: '项目规则',
  scope: '全局',
  category: 'coding_style',
  content: '使用双引号',
  enabled: true,
  editable: 'full',
  priority: 5,
  trigger: null,
  updatedAt: 1730000000000,
  origin: null,
};

const PLAYBOOK_ENTRY: RuleEntry = {
  id: 'playbook:s1:0',
  layer: 'playbook',
  sourceLabel: '规程 · 需求分析',
  scope: '全局',
  category: '需求',
  content: '先写用户故事',
  enabled: true,
  editable: 'readonly',
  priority: 5,
  trigger: null,
  updatedAt: null,
  origin: null,
};

const RULES: RuleEntry[] = [
  rule({ id: 'global:#0', layer: 'global', sourceLabel: '全局规则', content: '回答用中文' }),
  rule({
    id: 'doc:SAGE.md#0',
    layer: 'doc',
    sourceLabel: '项目总纲 SAGE.md',
    content: '提交前跑 pytest',
  }),
  rule({ ...CONSTRAINT_ENTRY, id: 'constraint:1' }),
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
  vi.clearAllMocks();
  list.mockReset().mockResolvedValue(RULES);
  effective.mockReset().mockResolvedValue({
    entries: RULES.filter((entry) => entry.enabled),
    conflicts: CONFLICTS,
  });
  create.mockReset().mockResolvedValue(undefined);
  update.mockReset().mockResolvedValue(undefined);
  remove.mockReset().mockResolvedValue(undefined);
  raw.mockReset().mockResolvedValue({ path: '', content: '', truncated: false });
  confirmDialog.mockReset().mockResolvedValue(true);
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

  it('shows the source file name with the full path as tooltip and drops the duplicated source name', async () => {
    list.mockResolvedValue([
      rule({
        id: 'doc:SAGE.md#0',
        layer: 'doc',
        sourceLabel: '项目总纲 SAGE.md',
        scope: '/home/fz/project/sage/SAGE.md',
        content: '提交前跑 pytest',
      }),
    ]);
    effective.mockResolvedValue({ entries: [], conflicts: [] });

    renderPanel();
    await screen.findByTestId('rules-group-doc');

    const row = screen.getByTestId('rule-row-doc:SAGE.md#0');
    expect(row.textContent).not.toContain('项目总纲 SAGE.md');
    const detail = screen.getByTitle('/home/fz/project/sage/SAGE.md');
    expect(detail.textContent).toBe('SAGE.md');
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

  it('opens the editor from the create button', async () => {
    renderPanel();
    await screen.findByTestId('rules-panel');

    fireEvent.click(screen.getByTestId('rules-create'));

    expect(await screen.findByTestId('rule-editor')).toBeInTheDocument();
  });

  it('hides edit and delete actions for read-only playbook rows', async () => {
    list.mockResolvedValue([PLAYBOOK_ENTRY]);
    effective.mockResolvedValue({ entries: [], conflicts: [] });
    renderPanel();

    const trigger = await screen.findByTestId(`rule-menu-${PLAYBOOK_ENTRY.id}`);
    fireEvent.pointerDown(trigger, { button: 0 });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });

    await waitFor(() =>
      expect(screen.queryByTestId(`rule-menu-copy-${PLAYBOOK_ENTRY.id}`)).not.toBeNull(),
    );
    expect(screen.queryByTestId(`rule-menu-edit-${PLAYBOOK_ENTRY.id}`)).toBeNull();
    expect(screen.queryByTestId(`rule-menu-delete-${PLAYBOOK_ENTRY.id}`)).toBeNull();
    const disabledEdit = screen.getByTestId(`rule-menu-edit-disabled-${PLAYBOOK_ENTRY.id}`);
    expect(disabledEdit).toBeInTheDocument();
    expect(disabledEdit).toHaveAttribute('aria-disabled', 'true');
  });

  it('toggles a constraint rule and reloads the list', async () => {
    renderPanel();

    const trigger = await screen.findByTestId(`rule-menu-${CONSTRAINT_ENTRY.id}`);
    fireEvent.pointerDown(trigger, { button: 0 });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    const toggle = await screen.findByTestId(`rule-menu-toggle-${CONSTRAINT_ENTRY.id}`);
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith('p-1', {
        layer: 'constraint',
        ruleId: CONSTRAINT_ENTRY.id,
        patch: { enabled: false },
        expectedUpdatedAt: CONSTRAINT_ENTRY.updatedAt,
      }),
    );
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  });

  it('reloads and reports a conflict instead of a generic toggle failure', async () => {
    update.mockRejectedValueOnce(
      Object.assign(new Error('规则已被修改（HTTP 409）'), { status_code: 409 }),
    );
    renderPanel();

    const trigger = await screen.findByTestId(`rule-menu-${CONSTRAINT_ENTRY.id}`);
    fireEvent.pointerDown(trigger, { button: 0 });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    fireEvent.click(await screen.findByTestId(`rule-menu-toggle-${CONSTRAINT_ENTRY.id}`));

    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(toast.error).toHaveBeenCalledWith('规则已被修改，列表已刷新，请重试');
    expect(toast.error).not.toHaveBeenCalledWith(expect.stringContaining('切换启用状态失败'));
  });

  it('skips deletion when the confirmation is declined', async () => {
    confirmDialog.mockResolvedValue(false);
    renderPanel();

    const trigger = await screen.findByTestId(`rule-menu-${CONSTRAINT_ENTRY.id}`);
    fireEvent.pointerDown(trigger, { button: 0 });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    fireEvent.click(await screen.findByTestId(`rule-menu-delete-${CONSTRAINT_ENTRY.id}`));

    await waitFor(() => expect(confirmDialog).toHaveBeenCalledOnce());
    expect(confirmDialog.mock.calls[0][0]).toMatchObject({ danger: true });
    expect(remove).not.toHaveBeenCalled();
  });

  it('deletes after confirmation and reloads', async () => {
    confirmDialog.mockResolvedValue(true);
    renderPanel();

    const trigger = await screen.findByTestId(`rule-menu-${CONSTRAINT_ENTRY.id}`);
    fireEvent.pointerDown(trigger, { button: 0 });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    fireEvent.click(await screen.findByTestId(`rule-menu-delete-${CONSTRAINT_ENTRY.id}`));

    await waitFor(() =>
      expect(remove).toHaveBeenCalledWith('p-1', 'constraint', CONSTRAINT_ENTRY.id),
    );
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  });

  it('reloads and reports a conflict instead of a generic delete failure', async () => {
    remove.mockRejectedValueOnce(
      Object.assign(new Error('规则已被修改（HTTP 409）'), { status_code: 409 }),
    );
    confirmDialog.mockResolvedValue(true);
    renderPanel();

    const trigger = await screen.findByTestId(`rule-menu-${CONSTRAINT_ENTRY.id}`);
    fireEvent.pointerDown(trigger, { button: 0 });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    fireEvent.click(await screen.findByTestId(`rule-menu-delete-${CONSTRAINT_ENTRY.id}`));

    await waitFor(() => expect(confirmDialog).toHaveBeenCalledOnce());
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(toast.error).toHaveBeenCalledWith('规则已被修改，列表已刷新，请重试');
    expect(toast.error).not.toHaveBeenCalledWith(expect.stringContaining('删除失败'));
  });

  it('copies rule content to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    renderPanel();

    const trigger = await screen.findByTestId(`rule-menu-${CONSTRAINT_ENTRY.id}`);
    fireEvent.pointerDown(trigger, { button: 0 });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    fireEvent.click(await screen.findByTestId(`rule-menu-copy-${CONSTRAINT_ENTRY.id}`));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(CONSTRAINT_ENTRY.content));
  });

  it('opens the AI drawer from the toolbar', async () => {
    list.mockResolvedValue([CONSTRAINT_ENTRY]);
    effective.mockResolvedValue({ entries: [], conflicts: [] });
    renderPanel();
    fireEvent.click(await screen.findByTestId('rules-ai-open'));
    expect(await screen.findByTestId('ai-drawer')).toBeInTheDocument();
    expect(screen.getByTestId('ai-instruction')).toHaveValue('');
  });

  it('opens the AI drawer focused on a rule from the row menu', async () => {
    list.mockResolvedValue([CONSTRAINT_ENTRY]);
    effective.mockResolvedValue({ entries: [], conflicts: [] });
    renderPanel();
    const trigger = await screen.findByTestId(`rule-menu-${CONSTRAINT_ENTRY.id}`);
    fireEvent.pointerDown(trigger, { button: 0 });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    fireEvent.click(await screen.findByTestId(`rule-menu-ai-${CONSTRAINT_ENTRY.id}`));
    expect(await screen.findByTestId('ai-drawer')).toBeInTheDocument();
    expect(screen.getByTestId('ai-instruction')).toHaveValue('改写这条规则：使用双引号');
  });
});
