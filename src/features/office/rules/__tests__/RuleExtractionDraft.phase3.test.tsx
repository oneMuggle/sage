// Phase 3 tests: confidence filter + bulk select (M20), manual rule creation
// (M15), and committing into an existing group with a same-name merge preview
// (M17/M18).
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { officeRulesApi } from '../../../../shared/api/officeRulesApi';
import type { WireDraftRuleItem, WireRuleGroup } from '../../../../shared/api/types';
import { RuleExtractionDraft } from '../RuleExtractionDraft';
import { useRuleDraftStore } from '../ruleDraftStore';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));
vi.mock('../../../../shared/api/officeRulesApi', () => ({
  officeRulesApi: {
    listGroups: vi.fn().mockResolvedValue([]),
    commitRules: vi.fn(),
    refineRules: vi.fn(),
  },
}));

const mockedListGroups = vi.mocked(officeRulesApi.listGroups);
const mockedCommit = vi.mocked(officeRulesApi.commitRules);

function draftItem(overrides: Partial<WireDraftRuleItem> = {}): WireDraftRuleItem {
  return {
    temp_id: 'draft_0',
    name: '正文字体',
    kind: 'style.font',
    params: { cjk_font: '宋体' },
    category: 'style',
    severity: 'warning',
    confidence: 0.95,
    source_excerpt: '',
    conflict_group: null,
    suggested_check_mode: 'ai',
    suggested_ai_prompt: '检查正文字体',
    suggested_type: 'format',
    suggested_scope: 'body',
    description: '',
    ...overrides,
  };
}

function seedDraft(items: WireDraftRuleItem[]) {
  const store = useRuleDraftStore.getState();
  store.reset();
  store.open('spec.docx', '/ws');
  store.setDraft(items, [], []);
}

function renderDraft() {
  const onCommitted = vi.fn();
  render(<RuleExtractionDraft onCommitted={onCommitted} />);
  return { onCommitted };
}

const EXISTING_GROUP: WireRuleGroup = {
  id: 'group-existing',
  name: '已有规则组',
  description: '',
  rules: [
    {
      id: 'rule-1',
      name: '正文字体',
      type: 'format',
      severity: 'warning',
      scope: 'body',
      description: '',
      check_mode: 'ai',
      pattern: null,
      ai_prompt: '检查正文字体',
      enabled: true,
      group_id: 'group-existing',
    },
  ],
  priority: 0,
  builtin: false,
};

beforeEach(() => {
  localStorage.clear();
  useRuleDraftStore.getState().reset();
  mockedListGroups.mockReset().mockResolvedValue([]);
  mockedCommit.mockReset();
});

describe('RuleExtractionDraft — Phase 3', () => {
  it('filters the list by confidence', () => {
    seedDraft([
      draftItem({ temp_id: 'draft_0', name: '正文字体', confidence: 0.95 }),
      draftItem({ temp_id: 'draft_1', name: '首行缩进', confidence: 0.3 }),
    ]);
    renderDraft();

    expect(screen.getByText('正文字体')).toBeInTheDocument();
    expect(screen.getByText('首行缩进')).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('rule-draft-confidence-filter'), {
      target: { value: 'high' },
    });

    expect(screen.getByText('正文字体')).toBeInTheDocument();
    expect(screen.queryByText('首行缩进')).toBeNull();
  });

  it('bulk-selects only high-confidence rules', () => {
    seedDraft([
      draftItem({ temp_id: 'draft_0', confidence: 0.95 }),
      draftItem({ temp_id: 'draft_1', name: '低置信规则', confidence: 0.3 }),
    ]);
    // 低置信度默认不选中；先全选再点"仅选高置信度"验证其会取消低置信选中。
    act(() => useRuleDraftStore.getState().selectAll());
    renderDraft();

    fireEvent.click(screen.getByTestId('rule-draft-select-high'));

    const rules = useRuleDraftStore.getState().rules;
    expect(rules.find((r) => r.tempId === 'draft_0')?.selected).toBe(true);
    expect(rules.find((r) => r.tempId === 'draft_1')?.selected).toBe(false);
  });

  it('adds a manual rule via the inline form', () => {
    seedDraft([draftItem()]);
    renderDraft();

    fireEvent.click(screen.getByTestId('rule-draft-add-toggle'));
    fireEvent.change(screen.getByTestId('rule-draft-add-name'), {
      target: { value: '参考文献格式' },
    });
    fireEvent.click(screen.getByTestId('rule-draft-add-confirm'));

    const rules = useRuleDraftStore.getState().rules;
    expect(rules).toHaveLength(2);
    const manual = rules[1];
    expect(manual.name).toBe('参考文献格式');
    expect(manual.selected).toBe(true);
    expect(manual.confidence).toBe(1);
    expect(manual.sourceExcerpt).toBe('手动添加');
  });

  it('skips same-name rules when committing into an existing group', async () => {
    mockedListGroups.mockResolvedValue([EXISTING_GROUP]);
    mockedCommit.mockResolvedValue({ group_id: 'group-existing', rules_created: 1 });
    seedDraft([
      draftItem({ temp_id: 'draft_0', name: '正文字体' }),
      draftItem({ temp_id: 'draft_1', name: '行间距', confidence: 0.9 }),
    ]);
    const { onCommitted } = renderDraft();

    // Wait for the group list to load, then pick the existing group.
    await waitFor(() => expect(screen.getByText('提交到：已有规则组')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('rule-draft-target-group'), {
      target: { value: 'group-existing' },
    });

    expect(screen.getByTestId('rule-draft-merge-preview')).toHaveTextContent(
      '将新增 1 条，跳过 1 条同名规则',
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /确认落盘/ }));
    });

    await waitFor(() => expect(mockedCommit).toHaveBeenCalledTimes(1));
    const payload = mockedCommit.mock.calls[0][0];
    expect(payload.target_group_id).toBe('group-existing');
    expect(payload.group_name).toBe('已有规则组');
    expect(payload.rules).toHaveLength(1);
    expect(payload.rules[0].name).toBe('行间距');
    expect(onCommitted).toHaveBeenCalledWith('group-existing', 1);
  });
});
