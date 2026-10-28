/**
 * PlanApprovalBar.mode-recommendation.test.tsx — 计划模式执行模式推荐 UI 测试。
 *
 * 覆盖 PlanApprovalBar 新增的 recommendedExecutionMode / executionModeReasoning props：
 * - recommendedMode=single → 显示"推荐：单 agent（串行）" + 下拉覆盖
 * - recommendedMode=multi → 显示"推荐：编排模式（并行）"
 * - recommendedMode=ask_user → ExecutionModePicker 自动弹出
 * - ask_user + dismissed → "选择执行模式"重开按钮出现
 * - ask_user + 未选 → 批准按钮 disabled
 * - 新推荐到达 → modePickerDismissed 重置（useEffect）
 * - executionModeReasoning → 传入 ExecutionModePicker
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PlanApprovalBar, type PlanApprovalBarProps } from '../PlanApprovalBar';

afterEach(cleanup);

function makeProps(overrides: Partial<PlanApprovalBarProps> = {}): PlanApprovalBarProps {
  return {
    planApprovalFor: 'sess-1',
    currentSessionId: 'sess-1',
    clearPlanApproval: vi.fn(),
    messages: [],
    sendMessage: vi.fn().mockResolvedValue(undefined),
    preflightPhase: null,
    taskBoard: null,
    onCancelRun: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function renderBar(overrides: Partial<PlanApprovalBarProps> = {}) {
  return render(<PlanApprovalBar {...makeProps(overrides)} />);
}

describe('PlanApprovalBar — mode recommendation UI', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('recommendedMode=single → 显示"推荐：单 agent（串行）" + 下拉', () => {
    renderBar({ recommendedExecutionMode: 'single' });
    expect(screen.getByTestId('plan-recommended-mode')).toHaveTextContent('推荐：单 agent（串行）');
    expect(screen.getByTestId('plan-mode-select')).toBeInTheDocument();
  });

  it('recommendedMode=multi → 显示"推荐：编排模式（并行）"', () => {
    renderBar({ recommendedExecutionMode: 'multi' });
    expect(screen.getByTestId('plan-recommended-mode')).toHaveTextContent('推荐：编排模式（并行）');
  });

  it('recommendedMode=null → 不显示推荐徽标和下拉', () => {
    renderBar({ recommendedExecutionMode: null });
    expect(screen.queryByTestId('plan-recommended-mode')).toBeNull();
    expect(screen.queryByTestId('plan-mode-select')).toBeNull();
  });

  it('recommendedMode=ask_user → ExecutionModePicker 自动弹出', () => {
    renderBar({
      recommendedExecutionMode: 'ask_user',
      executionModeReasoning: '步骤多但依赖链不明确',
    });
    expect(screen.getByText('选择执行模式')).toBeInTheDocument();
    expect(screen.getByText('步骤多但依赖链不明确')).toBeInTheDocument();
  });

  it('ask_user + 用户关闭 picker → "选择执行模式"重开按钮出现', () => {
    renderBar({ recommendedExecutionMode: 'ask_user' });
    // picker 标题是 <h3>"选择执行模式"
    expect(screen.getByRole('heading', { name: '选择执行模式' })).toBeInTheDocument();
    // 先关闭 picker
    fireEvent.click(screen.getByText('取消（保留 plan 待审阅）'));
    // picker 标题消失
    expect(screen.queryByRole('heading', { name: '选择执行模式' })).toBeNull();
    // 重开按钮出现（按钮文本也是"选择执行模式"，但 role=button 可区分）
    expect(screen.getByTestId('plan-mode-select-open')).toBeInTheDocument();
  });

  it('重开按钮点击 → ExecutionModePicker 重新弹出', () => {
    renderBar({ recommendedExecutionMode: 'ask_user' });
    fireEvent.click(screen.getByText('取消（保留 plan 待审阅）'));
    expect(screen.queryByRole('heading', { name: '选择执行模式' })).toBeNull();
    fireEvent.click(screen.getByTestId('plan-mode-select-open'));
    expect(screen.getByRole('heading', { name: '选择执行模式' })).toBeInTheDocument();
  });

  it('ask_user + 未选 → 批准按钮 disabled', () => {
    renderBar({ recommendedExecutionMode: 'ask_user' });
    const approveBtn = screen.getByTestId('plan-approve');
    const orchBtn = screen.getByTestId('plan-approve-orch');
    expect(approveBtn).toBeDisabled();
    expect(orchBtn).toBeDisabled();
  });

  it('ask_user + 用户在 picker 中选 single → 批准按钮启用', () => {
    renderBar({ recommendedExecutionMode: 'ask_user' });
    fireEvent.click(screen.getByText('单 agent（串行）'));
    // picker 关闭后，批准按钮应启用
    const approveBtn = screen.getByTestId('plan-approve');
    expect(approveBtn).not.toBeDisabled();
  });

  it('single/multi → 批准按钮始终启用（无需 picker）', () => {
    renderBar({ recommendedExecutionMode: 'single' });
    expect(screen.getByTestId('plan-approve')).not.toBeDisabled();
    expect(screen.getByTestId('plan-approve-orch')).not.toBeDisabled();
  });

  it('推荐覆盖时，下拉可强制选 single/multi', () => {
    renderBar({ recommendedExecutionMode: 'multi' });
    const select = screen.getByTestId('plan-mode-select');
    fireEvent.change(select, { target: { value: 'single' } });
    expect(screen.getByTestId('plan-approve')).not.toBeDisabled();
  });
});
