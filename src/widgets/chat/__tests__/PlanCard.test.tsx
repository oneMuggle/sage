// src/widgets/chat/__tests__/PlanCard.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Wave 3 C4 (2026-08-15): PlanCard handleStart/handleCancel 内部调
// orchRunClient.updatePlan/cancelRun;mock 掉避免真实 IPC 抛错。
vi.mock('../../../shared/api/orchRunClient', () => ({
  orchRunClient: {
    cancelRun: vi.fn(),
    updatePlan: vi.fn(),
  },
}));

import { PlanCard } from '../../../components/PlanCard';
import { orchRunClient } from '../../../shared/api/orchRunClient';
import type { TaskPlanItem } from '../../../shared/api/types';

const basePlan: TaskPlanItem[] = [{ task_id: 't1', agent_id: 'primary', goal: 'original goal' }];

describe('PlanCard (P1-5)', () => {
  it('renders items and allows goal edit', () => {
    render(
      <PlanCard runId="r1" plan={basePlan} locked={false} onCancel={() => {}} onStart={() => {}} />,
    );
    const textarea = screen.getByTestId('plan-goal-t1') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'edited goal' } });
    expect(textarea.value).toBe('edited goal');
  });

  it('remove button disabled when only one item', () => {
    render(
      <PlanCard runId="r1" plan={basePlan} locked={false} onCancel={() => {}} onStart={() => {}} />,
    );
    expect(screen.getByTestId('plan-remove-t1')).toBeDisabled();
  });

  it('locked mode disables editing + shows locked label', () => {
    render(
      <PlanCard runId="r1" plan={basePlan} locked={true} onCancel={() => {}} onStart={() => {}} />,
    );
    expect(screen.getByTestId('plan-goal-t1')).toBeDisabled();
    expect(screen.getByTestId('plan-start')).toHaveTextContent('已开始执行（计划锁定）');
  });

  it('remove button deletes row when multiple items', () => {
    const plan: TaskPlanItem[] = [
      { task_id: 't1', agent_id: 'primary', goal: 'g1' },
      { task_id: 't2', agent_id: 'writer', goal: 'g2' },
    ];
    render(
      <PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} onStart={() => {}} />,
    );
    fireEvent.click(screen.getByTestId('plan-remove-t1'));
    expect(screen.queryByTestId('plan-row-t1')).toBeNull();
    expect(screen.getByTestId('plan-row-t2')).toBeInTheDocument();
  });

  // C4 (2026-08-15): handleStart 内部先 await updatePlan 落库再 onStart,
  // onStart 在微任务中触发 → 断言改异步 waitFor。
  it('onStart carries edited plan items', async () => {
    const onStart = vi.fn();
    vi.mocked(orchRunClient.updatePlan).mockResolvedValue({ ok: true });
    render(
      <PlanCard runId="r1" plan={basePlan} locked={false} onCancel={() => {}} onStart={onStart} />,
    );
    const textarea = screen.getByTestId('plan-goal-t1') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'updated' } });
    fireEvent.click(screen.getByTestId('plan-start'));
    await waitFor(() =>
      expect(onStart).toHaveBeenCalledWith([
        { task_id: 't1', agent_id: 'primary', goal: 'updated' },
      ]),
    );
  });
});

// ===== Wave 3 C4 (2026-08-15): 交互接线 —— 开始执行落库 + 取消语义随 locked =====
describe('PlanCard 接线 (Wave 3 C4)', () => {
  const plan = [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }];

  it('未派发：取消 → onCancel（不调后端）', () => {
    const onCancel = vi.fn();
    render(
      <PlanCard runId="r1" plan={plan} locked={false} onCancel={onCancel} onStart={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId('plan-cancel'));
    expect(onCancel).toHaveBeenCalled();
    expect(orchRunClient.cancelRun).not.toHaveBeenCalled();
  });

  it('已派发：按钮文案「取消执行」→ cancelRun + onCancelled', async () => {
    const onCancelled = vi.fn();
    vi.mocked(orchRunClient.cancelRun).mockResolvedValue({
      ok: true,
      run_id: 'r1',
      status: 'cancelled',
    });
    render(
      <PlanCard
        runId="r1"
        plan={plan}
        locked
        onCancel={() => {}}
        onStart={vi.fn()}
        onCancelled={onCancelled}
      />,
    );
    expect(screen.getByTestId('plan-cancel')).toHaveTextContent('取消执行');
    fireEvent.click(screen.getByTestId('plan-cancel'));
    await waitFor(() => expect(orchRunClient.cancelRun).toHaveBeenCalledWith('r1'));
    expect(onCancelled).toHaveBeenCalled();
  });

  it('开始执行 → updatePlan 落库 + 本地锁定', async () => {
    vi.mocked(orchRunClient.updatePlan).mockResolvedValue({ ok: true });
    render(
      <PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} onStart={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId('plan-start'));
    await waitFor(() =>
      expect(orchRunClient.updatePlan).toHaveBeenCalledWith('r1', expect.any(Array)),
    );
    // 锁定后开始按钮 disabled + 文案「已开始执行」
    await waitFor(() => expect(screen.getByTestId('plan-start')).toBeDisabled());
  });
});
