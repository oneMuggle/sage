import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  PatchApplyResponse,
  PatchOperation,
  PatchPreviewResponse,
} from '../../../shared/api/rulesApi';
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

const { previewPatch, applyPatch, confirmDialog } = vi.hoisted(() => ({
  previewPatch: vi.fn(),
  applyPatch: vi.fn(),
  confirmDialog: vi.fn(),
}));

vi.mock('../../../shared/api/rulesApi', () => ({
  rulesApi: { previewPatch, applyPatch },
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({ confirmDialog }));

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
    confirmDialog.mockReset();
    confirmDialog.mockResolvedValue(true);
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
    expect(screen.getByTestId('ai-apply-summary')).toHaveTextContent('已应用 1 条修改');
  });

  it('discards an in-flight preview that resolves after the drawer was reopened', async () => {
    let resolvePreview: (value: PatchPreviewResponse) => void = () => {};
    previewPatch.mockReturnValue(
      new Promise<PatchPreviewResponse>((resolve) => {
        resolvePreview = resolve;
      }),
    );
    const { rerender } = renderDrawer();
    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '旧指令' } });
    fireEvent.click(screen.getByTestId('ai-generate'));
    expect(screen.getByTestId('ai-generate')).toBeDisabled();

    const props = { onClose: () => {}, projectId: 'p1', onApplied: vi.fn() };
    rerender(
      <I18nProvider defaultLocale="zh">
        <AiRulePatchDrawer isOpen={false} {...props} />
      </I18nProvider>,
    );
    rerender(
      <I18nProvider defaultLocale="zh">
        <AiRulePatchDrawer isOpen {...props} />
      </I18nProvider>,
    );

    await act(async () => {
      resolvePreview(preview());
    });

    expect(screen.queryByTestId('patch-card-op-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('ai-apply')).not.toBeInTheDocument();
    // 重开的会话没有被上一轮在途请求卡在“分析中”。
    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '新指令' } });
    expect(screen.getByTestId('ai-generate')).not.toBeDisabled();
  });

  it('prevents generating and applying at the same time', async () => {
    let resolvePreview: (value: PatchPreviewResponse) => void = () => {};
    previewPatch.mockReturnValue(
      new Promise<PatchPreviewResponse>((resolve) => {
        resolvePreview = resolve;
      }),
    );
    renderDrawer();
    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '改一下' } });
    fireEvent.click(screen.getByTestId('ai-generate'));

    expect(screen.getByTestId('ai-generate')).toBeDisabled();
    // 生成期间旧卡片与旧的应用入口都不会残留。
    expect(screen.queryByTestId('ai-apply')).not.toBeInTheDocument();

    await act(async () => {
      resolvePreview(preview());
    });
    await screen.findByTestId('patch-card-op-1');

    let resolveApply: (value: PatchApplyResponse) => void = () => {};
    applyPatch.mockReturnValue(
      new Promise<PatchApplyResponse>((resolve) => {
        resolveApply = resolve;
      }),
    );
    fireEvent.click(screen.getByTestId('ai-apply'));
    expect(screen.getByTestId('ai-generate')).toBeDisabled();
    expect(screen.getByTestId('ai-apply')).toBeDisabled();

    await act(async () => {
      resolveApply({
        results: [{ opId: 'op-1', status: 'applied', message: '', current: null }],
        applied: 1,
        failed: 0,
      });
    });
    expect(screen.getByTestId('ai-generate')).not.toBeDisabled();
  });

  it('reports a partial apply summary when some operations fail', async () => {
    previewPatch.mockResolvedValue(
      preview({ operations: [operation({ opId: 'op-1' }), operation({ opId: 'op-2' })] }),
    );
    applyPatch.mockResolvedValue({
      results: [
        { opId: 'op-1', status: 'applied', message: '', current: null },
        { opId: 'op-2', status: 'invalid', message: '格式错误', current: null },
      ],
      applied: 1,
      failed: 1,
    });
    renderDrawer();

    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '改一下' } });
    fireEvent.click(screen.getByTestId('ai-generate'));
    await screen.findByTestId('patch-card-op-1');
    fireEvent.click(screen.getByTestId('ai-apply'));

    expect(await screen.findByTestId('ai-apply-summary')).toHaveTextContent(
      '已应用 1 条，1 条未应用',
    );
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

  it('asks for confirmation before applying selected delete operations', async () => {
    previewPatch.mockResolvedValue(
      preview({
        operations: [
          operation({ opId: 'op-1' }),
          operation({ opId: 'op-2', action: 'delete', after: {} }),
        ],
      }),
    );
    applyPatch.mockResolvedValue({
      results: [{ opId: 'op-2', status: 'applied', message: '', current: null }],
      applied: 1,
      failed: 0,
    });
    renderDrawer();

    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '去重' } });
    fireEvent.click(screen.getByTestId('ai-generate'));
    await screen.findByTestId('patch-card-op-1');
    fireEvent.click(screen.getByTestId('patch-select-op-2'));
    fireEvent.click(screen.getByTestId('ai-apply'));

    await waitFor(() => expect(confirmDialog).toHaveBeenCalledTimes(1));
    expect(confirmDialog.mock.calls[0][0]).toMatchObject({ danger: true });
    expect(confirmDialog.mock.calls[0][0].message).toContain('1');
    await waitFor(() => expect(applyPatch).toHaveBeenCalledTimes(1));
  });

  it('does not apply when the delete confirmation is cancelled', async () => {
    previewPatch.mockResolvedValue(
      preview({
        operations: [
          operation({ opId: 'op-1' }),
          operation({ opId: 'op-2', action: 'delete', after: {} }),
        ],
      }),
    );
    confirmDialog.mockResolvedValue(false);
    renderDrawer();

    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '去重' } });
    fireEvent.click(screen.getByTestId('ai-generate'));
    await screen.findByTestId('patch-card-op-1');
    fireEvent.click(screen.getByTestId('patch-select-op-2'));
    fireEvent.click(screen.getByTestId('ai-apply'));

    await waitFor(() => expect(confirmDialog).toHaveBeenCalledTimes(1));
    expect(applyPatch).not.toHaveBeenCalled();
  });

  it('does not ask for confirmation when no delete operation is selected', async () => {
    previewPatch.mockResolvedValue(preview());
    applyPatch.mockResolvedValue({
      results: [{ opId: 'op-1', status: 'applied', message: '', current: null }],
      applied: 1,
      failed: 0,
    });
    renderDrawer();

    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '改一下' } });
    fireEvent.click(screen.getByTestId('ai-generate'));
    await screen.findByTestId('patch-card-op-1');
    fireEvent.click(screen.getByTestId('ai-apply'));

    await waitFor(() => expect(applyPatch).toHaveBeenCalledTimes(1));
    expect(confirmDialog).not.toHaveBeenCalled();
  });

  it('surfaces preview failures instead of silently showing an empty list', async () => {
    previewPatch.mockRejectedValue(new Error('AI 返回格式不正确，请重试或手动编辑'));
    renderDrawer();

    fireEvent.change(screen.getByTestId('ai-instruction'), { target: { value: '改一下' } });
    fireEvent.click(screen.getByTestId('ai-generate'));

    expect(await screen.findByTestId('ai-error')).toHaveTextContent('AI 返回格式不正确');
  });
});
