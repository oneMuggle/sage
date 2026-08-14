// src/widgets/chat/__tests__/PlanCard.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PlanCard } from '../../../components/PlanCard';
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

  it('onStart carries edited plan items', () => {
    const onStart = vi.fn();
    render(
      <PlanCard runId="r1" plan={basePlan} locked={false} onCancel={() => {}} onStart={onStart} />,
    );
    const textarea = screen.getByTestId('plan-goal-t1') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'updated' } });
    fireEvent.click(screen.getByTestId('plan-start'));
    expect(onStart).toHaveBeenCalledWith([{ task_id: 't1', agent_id: 'primary', goal: 'updated' }]);
  });
});
