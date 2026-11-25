// Tests for RuleRefinePanel: natural-language instruction → diff cards →
// accept applies the action to the draft store.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { officeRulesApi } from '../../../../shared/api/officeRulesApi';
import type { WireRefineResult } from '../../../../shared/api/types';
import { RuleRefinePanel } from '../RuleRefinePanel';
import { useRuleDraftStore } from '../ruleDraftStore';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));
vi.mock('../../../../shared/api/officeRulesApi', () => ({
  officeRulesApi: {
    refineRules: vi.fn(),
  },
}));

const mockedRefine = vi.mocked(officeRulesApi.refineRules);

function seedDraft() {
  useRuleDraftStore.getState().reset();
  useRuleDraftStore.getState().setDraft(
    [
      {
        temp_id: 'draft_0',
        name: '行间距',
        kind: 'style.paragraph',
        params: { line_spacing_pt: 20 },
        category: 'style',
        severity: 'warning',
        confidence: 0.8,
        source_excerpt: '',
        conflict_group: null,
        suggested_check_mode: 'ai',
        suggested_ai_prompt: '检查行间距',
        suggested_type: 'format',
        suggested_scope: 'body',
        description: '',
      },
    ],
    [],
    [],
  );
}

describe('RuleRefinePanel', () => {
  beforeEach(() => {
    seedDraft();
    mockedRefine.mockReset();
  });

  it('sends the instruction and applies an accepted modify action', async () => {
    mockedRefine.mockResolvedValue({
      actions: [
        {
          type: 'modify',
          temp_id: 'draft_0',
          patch: { params: { line_spacing_pt: 30 } },
          explanation: '间距改为 30pt',
        },
      ],
      warnings: [],
    } as WireRefineResult);

    render(<RuleRefinePanel />);

    const input = screen.getByTestId('rule-refine-input');
    fireEvent.change(input, { target: { value: '行间距改成30pt' } });
    await act(async () => {
      fireEvent.click(screen.getByText('发送'));
    });

    await waitFor(() => expect(mockedRefine).toHaveBeenCalledTimes(1));
    // The request carries the current draft rules.
    const payload = mockedRefine.mock.calls[0][0];
    expect(payload.instruction).toBe('行间距改成30pt');
    expect(payload.rules[0]).toMatchObject({ temp_id: 'draft_0', name: '行间距' });

    // Diff card shows the before → after values.
    await waitFor(() => expect(screen.getByTestId('rule-diff-card')).toBeInTheDocument());
    expect(screen.getByText('20')).toBeInTheDocument();
    expect(screen.getByText('30')).toBeInTheDocument();

    // Accept applies the action to the draft store.
    await act(async () => {
      fireEvent.click(screen.getByText('接受'));
    });
    const updated = useRuleDraftStore.getState().rules[0];
    expect(updated.params).toEqual({ line_spacing_pt: 30 });
    expect(updated.dirty).toBe(true);
  });

  it('adds a new rule when an add action is accepted', async () => {
    mockedRefine.mockResolvedValue({
      actions: [
        {
          type: 'add',
          rule: { name: '参考文献格式', kind: 'content.citation' },
          explanation: '补充引用规范',
        },
      ],
      warnings: [],
    } as WireRefineResult);

    render(<RuleRefinePanel />);
    fireEvent.change(screen.getByTestId('rule-refine-input'), {
      target: { value: '加上参考文献格式要求' },
    });
    await act(async () => {
      fireEvent.click(screen.getByText('发送'));
    });
    await waitFor(() => expect(screen.getByTestId('rule-diff-card')).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByText('接受'));
    });
    const rules = useRuleDraftStore.getState().rules;
    expect(rules).toHaveLength(2);
    expect(rules[1].name).toBe('参考文献格式');
    expect(rules[1].selected).toBe(true);
  });

  it('rejecting the action leaves the draft untouched', async () => {
    mockedRefine.mockResolvedValue({
      actions: [{ type: 'delete', temp_id: 'draft_0', explanation: '这条不需要' }],
      warnings: [],
    } as WireRefineResult);

    render(<RuleRefinePanel />);
    fireEvent.change(screen.getByTestId('rule-refine-input'), {
      target: { value: '去掉行间距规则' },
    });
    await act(async () => {
      fireEvent.click(screen.getByText('发送'));
    });
    await waitFor(() => expect(screen.getByTestId('rule-diff-card')).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByText('拒绝'));
    });
    expect(useRuleDraftStore.getState().rules).toHaveLength(1);
  });
});
