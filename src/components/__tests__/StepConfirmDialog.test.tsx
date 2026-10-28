/**
 * StepConfirmDialog.test.tsx — 步骤确认对话框组件测试（2026-10-28）。
 *
 * 覆盖：
 * - 渲染当前步骤 goal
 * - 渲染影响预估（impact）
 * - 渲染触发规则类别标签
 * - 渲染上一步输出
 * - 渲染下一步预览
 * - 三个按钮点击 → onConfirm 回调
 * - 不传 impact 时不渲染影响区
 * - 不传 categories 时不渲染规则区
 * - 不传 previousOutput 时不渲染上一步区
 * - 不传 nextStepPreview 时不渲染下一步区
 * - category label 映射（中英文）
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { StepConfirmDialog, type StepConfirmInfo } from '../StepConfirmDialog';

afterEach(cleanup);

// ── Fixtures ───────────────────────────────────────────────────────────────────

function makeStep(overrides: Partial<StepConfirmInfo> = {}): StepConfirmInfo {
  return {
    goal: 'rm -rf ./dist 清理构建产物',
    stepId: 'step-1',
    impact: '将删除 3 个文件',
    categories: ['file_delete'],
    previousOutput: '上一步：生成构建产物完成',
    nextStepPreview: '下一步：运行测试套件',
    ...overrides,
  };
}

// ── Rendering ──────────────────────────────────────────────────────────────────

describe('StepConfirmDialog', () => {
  it('渲染当前步骤 goal', () => {
    render(<StepConfirmDialog step={makeStep()} onConfirm={vi.fn()} />);
    expect(screen.getByTestId('step-goal')).toHaveTextContent('rm -rf ./dist 清理构建产物');
  });

  it('渲染影响预估', () => {
    render(<StepConfirmDialog step={makeStep()} onConfirm={vi.fn()} />);
    expect(screen.getByTestId('step-impact')).toHaveTextContent('将删除 3 个文件');
  });

  it('渲染触发规则类别标签', () => {
    render(
      <StepConfirmDialog
        step={makeStep({ categories: ['file_delete', 'privileged'] })}
        onConfirm={vi.fn()}
      />,
    );
    const container = screen.getByTestId('step-categories');
    expect(container).toHaveTextContent('文件删除');
    expect(container).toHaveTextContent('特权操作');
  });

  it('渲染上一步输出', () => {
    render(<StepConfirmDialog step={makeStep()} onConfirm={vi.fn()} />);
    expect(screen.getByTestId('step-previous-output')).toHaveTextContent('生成构建产物完成');
  });

  it('渲染下一步预览', () => {
    render(<StepConfirmDialog step={makeStep()} onConfirm={vi.fn()} />);
    expect(screen.getByTestId('step-next-preview')).toHaveTextContent('运行测试套件');
  });

  // ── Actions ───────────────────────────────────────────────────────────────

  it('"继续" 按钮触发 onConfirm("continue")', () => {
    const onConfirm = vi.fn();
    render(<StepConfirmDialog step={makeStep()} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByTestId('step-confirm-continue'));
    expect(onConfirm).toHaveBeenCalledWith('continue');
  });

  it('"跳过此步" 按钮触发 onConfirm("skip")', () => {
    const onConfirm = vi.fn();
    render(<StepConfirmDialog step={makeStep()} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByTestId('step-confirm-skip'));
    expect(onConfirm).toHaveBeenCalledWith('skip');
  });

  it('"终止全部" 按钮触发 onConfirm("abort")', () => {
    const onConfirm = vi.fn();
    render(<StepConfirmDialog step={makeStep()} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByTestId('step-confirm-abort'));
    expect(onConfirm).toHaveBeenCalledWith('abort');
  });

  // ── Conditional rendering ─────────────────────────────────────────────────

  it('不传 impact 时不渲染影响区', () => {
    render(<StepConfirmDialog step={makeStep({ impact: undefined })} onConfirm={vi.fn()} />);
    expect(screen.queryByTestId('step-impact')).not.toBeInTheDocument();
  });

  it('不传 categories 时不渲染规则区', () => {
    render(<StepConfirmDialog step={makeStep({ categories: undefined })} onConfirm={vi.fn()} />);
    expect(screen.queryByTestId('step-categories')).not.toBeInTheDocument();
  });

  it('不传 previousOutput 时不渲染上一步区', () => {
    render(
      <StepConfirmDialog step={makeStep({ previousOutput: undefined })} onConfirm={vi.fn()} />,
    );
    expect(screen.queryByTestId('step-previous-output')).not.toBeInTheDocument();
  });

  it('不传 nextStepPreview 时不渲染下一步区', () => {
    render(
      <StepConfirmDialog step={makeStep({ nextStepPreview: undefined })} onConfirm={vi.fn()} />,
    );
    expect(screen.queryByTestId('step-next-preview')).not.toBeInTheDocument();
  });

  // ── Category label mapping ────────────────────────────────────────────────

  it('未知 category 直接显示原始值', () => {
    render(
      <StepConfirmDialog step={makeStep({ categories: ['unknown_rule'] })} onConfirm={vi.fn()} />,
    );
    expect(screen.getByTestId('step-categories')).toHaveTextContent('unknown_rule');
  });

  it('空 categories 数组时不渲染规则区', () => {
    render(<StepConfirmDialog step={makeStep({ categories: [] })} onConfirm={vi.fn()} />);
    expect(screen.queryByTestId('step-categories')).not.toBeInTheDocument();
  });
});
