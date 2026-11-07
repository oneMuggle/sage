import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PatchOperation, PatchPreviewResponse } from '../../../shared/api/rulesApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { AiRulePatchDrawer, initialSelection } from '../AiRulePatchDrawer';

// jsdom 不实现 ResizeObserver，但 @headlessui Dialog 内部使用它
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

const { previewPatch, applyPatch } = vi.hoisted(() => ({
  previewPatch: vi.fn(),
  applyPatch: vi.fn(),
}));

vi.mock('../../../shared/api/rulesApi', () => ({
  rulesApi: { previewPatch, applyPatch },
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ENTRY = {
  id: 'constraint:1',
  layer: 'constraint' as const,
  sourceLabel: '项目规则',
  scope: '全局',
  category: 'coding_style',
  content: '使用单引号',
  enabled: true,
  editable: 'full' as const,
  priority: 5,
  trigger: null,
  updatedAt: 1730000000000,
  origin: null,
};

function operation(overrides: Partial<PatchOperation>): PatchOperation {
  return {
    opId: 'op-1',
    action: 'update',
    layer: 'constraint',
    ruleId: 'constraint:1',
    before: { content: '使用单引号' },
    after: { content: '使用双引号' },
    reason: '统一风格',
    expectedUpdatedAt: 1730000000000,
    error: null,
    ...overrides,
  };
}

function preview(overrides: Partial<PatchPreviewResponse> = {}): PatchPreviewResponse {
  return { llmAvailable: true, message: '', operations: [operation({})], ...overrides };
}

function renderDrawer(props: Partial<ComponentProps<typeof AiRulePatchDrawer>> = {}) {
  return render(
    <I18nProvider defaultLocale="zh">
      <AiRulePatchDrawer isOpen onClose={() => {}} projectId="p1" onApplied={vi.fn()} {...props} />
    </I18nProvider>,
  );
}

describe('initialSelection', () => {
  it('selects executable non-delete operations only', () => {
    const selection = initialSelection([
      operation({ opId: 'a' }),
      operation({ opId: 'b', action: 'delete' }),
      operation({ opId: 'c', error: 'readonly_layer', layer: 'playbook' }),
    ]);
    expect(selection).toEqual({ a: true, b: false, c: false });
  });
});

describe('AiRulePatchDrawer', () => {
  beforeEach(() => {
    previewPatch.mockReset();
    applyPatch.mockReset();
  });

  it('prefills the focused rule and sends its id', async () => {
    previewPatch.mockResolvedValue(preview());
    renderDrawer({ focusEntry: ENTRY });

    expect(screen.getByTestId('ai-instruction')).toHaveValue('改写这条规则：使用单引号');
    fireEvent.click(screen.getByTestId('ai-generate'));

    await waitFor(() =>
      expect(previewPatch).toHaveBeenCalledWith('p1', {
        instruction: '改写这条规则：使用单引号',
        ruleId: 'constraint:1',
      }),
    );
    expect(await screen.findByTestId('patch-card-op-1')).toBeInTheDocument();
  });

  it('submits only the selected operations and reports the count', async () => {
    previewPatch.mockResolvedValue(
      preview({
        operations: [
          operation({ opId: 'op-1' }),
          operation({ opId: 'op-2', action: 'delete', after: {} }),
        ],
      }),
    );
    applyPatch.mockResolvedValue({
      results: [{ opId: 'op-1', status: 'applied', message: '', current: null }],
      applied: 1,
      failed: 0,
    });
    const onApplied = vi.fn();
    renderDrawer({ onApplied });

    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '去重' } });
    fireEvent.click(screen.getByTestId('ai-generate'));
    await screen.findByTestId('patch-card-op-1');

    expect(screen.getByTestId('patch-select-op-2')).not.toBeChecked();
    fireEvent.click(screen.getByTestId('ai-apply'));

    await waitFor(() => expect(applyPatch).toHaveBeenCalledTimes(1));
    const [, payload] = applyPatch.mock.calls[0];
    expect(payload.operations.map((item: PatchOperation) => item.opId)).toEqual(['op-1']);
    expect(onApplied).toHaveBeenCalled();
    expect(await screen.findByTestId('patch-result-op-1')).toHaveTextContent('已应用');
  });

  it('keeps conflicted operations visible with the current value', async () => {
    previewPatch.mockResolvedValue(preview());
    applyPatch.mockResolvedValue({
      results: [
        {
          opId: 'op-1',
          status: 'conflict',
          message: '规则已被修改',
          current: { content: '别处的当前值' },
        },
      ],
      applied: 0,
      failed: 1,
    });
    const onApplied = vi.fn();
    renderDrawer({ onApplied });

    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '改一下' } });
    fireEvent.click(screen.getByTestId('ai-generate'));
    await screen.findByTestId('patch-card-op-1');
    fireEvent.click(screen.getByTestId('ai-apply'));

    expect(await screen.findByTestId('patch-current-op-1')).toHaveTextContent('别处的当前值');
    expect(screen.getByTestId('patch-result-op-1')).toHaveTextContent('冲突');
    expect(onApplied).not.toHaveBeenCalled();
  });

  it('explains when the LLM is unavailable', async () => {
    previewPatch.mockResolvedValue(
      preview({ llmAvailable: false, message: 'AI 暂不可用，可手动编辑', operations: [] }),
    );
    renderDrawer();

    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '改一下' } });
    fireEvent.click(screen.getByTestId('ai-generate'));

    expect(await screen.findByTestId('ai-message')).toHaveTextContent('AI 暂不可用，可手动编辑');
    expect(screen.queryByTestId('ai-apply')).not.toBeInTheDocument();
  });

  it('surfaces preview failures instead of silently showing an empty list', async () => {
    previewPatch.mockRejectedValue(new Error('AI 返回格式不正确，请重试或手动编辑'));
    renderDrawer();

    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '改一下' } });
    fireEvent.click(screen.getByTestId('ai-generate'));

    expect(await screen.findByTestId('ai-error')).toHaveTextContent('AI 返回格式不正确');
  });
});
