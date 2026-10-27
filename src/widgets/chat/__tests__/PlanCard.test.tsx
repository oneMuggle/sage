// src/widgets/chat/__tests__/PlanCard.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Wave 3 C4+H1 (2026-08-15): PlanCard handleStart 内部调
// orchRunClient.updatePlan;取消语义统一委托上层 onCancel
// （Chat.handleCancelRun 负责 cancelRun + 清空 taskBoard），
// 故本文件断言"不调 cancelRun + onCancel 被调"。
// Fix #3 (2026-09-06): PlanCard.handleStart 在 needConfirm 模式下会调
// orchRunClient.confirmRun(runId) 唤醒后端 producer,本文件 mock 补齐 confirmRun。
vi.mock('../../../shared/api/orchRunClient', () => ({
  orchRunClient: {
    cancelRun: vi.fn(),
    updatePlan: vi.fn(),
    confirmRun: vi.fn(),
  },
}));

import { formatPlanCardJson, formatPlanCardMarkdown, PlanCard } from '../../../components/PlanCard';
import { orchRunClient } from '../../../shared/api/orchRunClient';
import type { TaskPlanItem } from '../../../shared/api/types';

const basePlan: TaskPlanItem[] = [{ task_id: 't1', agent_id: 'primary', goal: 'original goal' }];

describe('PlanCard (P1-5)', () => {
  it('renders items and allows goal edit', () => {
    render(<PlanCard runId="r1" plan={basePlan} locked={false} onCancel={() => {}} />);
    const textarea = screen.getByTestId('plan-goal-t1') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'edited goal' } });
    expect(textarea.value).toBe('edited goal');
  });

  it('remove button disabled when only one item', () => {
    render(<PlanCard runId="r1" plan={basePlan} locked={false} onCancel={() => {}} />);
    expect(screen.getByTestId('plan-remove-t1')).toBeDisabled();
  });

  it('locked mode disables editing + shows locked label', () => {
    render(<PlanCard runId="r1" plan={basePlan} locked={true} onCancel={() => {}} />);
    expect(screen.getByTestId('plan-goal-t1')).toBeDisabled();
    expect(screen.getByTestId('plan-start')).toHaveTextContent('已开始执行（计划锁定）');
  });

  it('remove button deletes row when multiple items', () => {
    const plan: TaskPlanItem[] = [
      { task_id: 't1', agent_id: 'primary', goal: 'g1' },
      { task_id: 't2', agent_id: 'writer', goal: 'g2' },
    ];
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} />);
    fireEvent.click(screen.getByTestId('plan-remove-t1'));
    expect(screen.queryByTestId('plan-row-t1')).toBeNull();
    expect(screen.getByTestId('plan-row-t2')).toBeInTheDocument();
  });

  // M4 (2026-08-15): onStart 链已收口删除 —— 编辑后计划落库断言并入
  // 下方"开始执行"接线测试（toHaveBeenCalledTimes(1) 直接验证单次 updatePlan）。
});

// ===== Wave 3 C4+H1 (2026-08-15): 交互接线 —— 开始执行落库 + 取消统一委托上层 =====
describe('PlanCard 接线 (Wave 3 C4+H1)', () => {
  const plan = [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }];

  it('未派发：取消 → onCancel 委托（不调后端）', () => {
    const onCancel = vi.fn();
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={onCancel} />);
    fireEvent.click(screen.getByTestId('plan-cancel'));
    expect(onCancel).toHaveBeenCalled();
    expect(orchRunClient.cancelRun).not.toHaveBeenCalled();
  });

  it('已派发：按钮文案「取消执行」→ 同样 onCancel 委托（统一取消语义）', () => {
    const onCancel = vi.fn();
    render(<PlanCard runId="r1" plan={plan} locked onCancel={onCancel} />);
    expect(screen.getByTestId('plan-cancel')).toHaveTextContent('取消执行');
    fireEvent.click(screen.getByTestId('plan-cancel'));
    expect(onCancel).toHaveBeenCalled();
    // H1：cancelRun 不在 PlanCard 内部调（统一交给上层 Chat.handleCancelRun）
    expect(orchRunClient.cancelRun).not.toHaveBeenCalled();
  });

  // M4 (2026-08-15): 收口 —— onStart 链已删，PlanCard.handleStart 是唯一的
  // updatePlan 调用点。断言编辑后计划落库（本地编辑在派发前持久化到后端权威
  // 计划）+ toHaveBeenCalledTimes(1) 直接验证无双调用。
  // 编排计划卡片 UX (2026-10-26): 成功后乐观折叠成一行摘要（不再霸占会话区），
  // 原"plan-start 禁用"断言改为折叠摘要断言。
  it('开始执行 → 编辑后计划 updatePlan 落库（单次）+ 乐观折叠', async () => {
    vi.mocked(orchRunClient.updatePlan).mockResolvedValue({ ok: true });
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} />);
    const textarea = screen.getByTestId('plan-goal-t1') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'updated' } });
    fireEvent.click(screen.getByTestId('plan-start'));
    // 单次落库 + 编辑后计划（M4 修复前此处会双调 updatePlan）
    await waitFor(() => expect(orchRunClient.updatePlan).toHaveBeenCalledTimes(1));
    expect(orchRunClient.updatePlan).toHaveBeenCalledWith('r1', [
      { task_id: 't1', agent_id: 'researcher', goal: 'updated' },
    ]);
    await waitFor(() => expect(screen.getByTestId('plan-card-collapsed')).toBeInTheDocument());
  });
});

// ===== §13.7 延后项 (2026-08-15): C4 双击守卫 + 错误区分 =====
describe('PlanCard §13.7 (C4 双击 + 错误处理)', () => {
  const plan = [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }];

  // 本项目 vitest 未开 clearMocks：同文件 mock 调用计数跨测试累积，
  // 上游用例的 updatePlan 调用会混入本块 toHaveBeenCalledTimes 断言
  // （实测双击用例收到 2/4/5 次累积计数）→ 每测前清一次调用计数。
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('双击开始执行 → updatePlan 只调一次（ref 同步防重入）', async () => {
    vi.mocked(orchRunClient.updatePlan).mockResolvedValue({ ok: true });
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} />);
    const btn = screen.getByTestId('plan-start');
    fireEvent.click(btn);
    fireEvent.click(btn); // 双击：第二击在 await 完成前被同步拦截
    await waitFor(() => expect(orchRunClient.updatePlan).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId('plan-card-collapsed')).toBeInTheDocument());
  });

  it('非 409 落库失败 → toast 提示 + 保持编辑态可重试', async () => {
    const toastErrorSpy = vi.spyOn(toast, 'error').mockImplementation(() => '');
    vi.mocked(orchRunClient.updatePlan)
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ ok: true });
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} />);
    const btn = screen.getByTestId('plan-start');
    fireEvent.click(btn);
    await waitFor(() =>
      expect(toastErrorSpy).toHaveBeenCalledWith(expect.stringContaining('计划保存失败')),
    );
    // ref 已复位 → 再点可成功
    fireEvent.click(btn);
    await waitFor(() => expect(orchRunClient.updatePlan).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByTestId('plan-card-collapsed')).toBeInTheDocument());
    toastErrorSpy.mockRestore();
  });

  it('409 落库失败 → 静默（不 toast）保持编辑态', async () => {
    const toastErrorSpy = vi.spyOn(toast, 'error').mockImplementation(() => '');
    const err409 = new Error(
      'Backend POST http://x/runs/r1/plan → 409: plan locked after dispatch',
    ) as Error & {
      status_code?: number;
    };
    err409.status_code = 409;
    vi.mocked(orchRunClient.updatePlan).mockRejectedValueOnce(err409);
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} />);
    const btn = screen.getByTestId('plan-start');
    fireEvent.click(btn);
    await waitFor(() => expect(orchRunClient.updatePlan).toHaveBeenCalledTimes(1));
    expect(toastErrorSpy).not.toHaveBeenCalled();
    expect(btn).not.toBeDisabled(); // 保持编辑态
    toastErrorSpy.mockRestore();
  });
});

// ===== Fix #3 (2026-09-06): needConfirm 模式 —— 用户显式确认才触发执行 =====
describe('PlanCard needConfirm (Fix #3)', () => {
  const plan = [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('needConfirm=true: 开始执行 → updatePlan + confirmRun 依次调用', async () => {
    vi.mocked(orchRunClient.updatePlan).mockResolvedValue({ ok: true });
    vi.mocked(orchRunClient.confirmRun).mockResolvedValue({ ok: true });
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} needConfirm />);
    fireEvent.click(screen.getByTestId('plan-start'));
    await waitFor(() => expect(orchRunClient.updatePlan).toHaveBeenCalledWith('r1', plan));
    await waitFor(() => expect(orchRunClient.confirmRun).toHaveBeenCalledWith('r1'));
    // confirmRun 调成功后乐观折叠
    await waitFor(() => expect(screen.getByTestId('plan-card-collapsed')).toBeInTheDocument());
  });

  it('needConfirm=false (默认): 开始执行 → 只调 updatePlan,不调 confirmRun', async () => {
    vi.mocked(orchRunClient.updatePlan).mockResolvedValue({ ok: true });
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} />);
    fireEvent.click(screen.getByTestId('plan-start'));
    await waitFor(() => expect(orchRunClient.updatePlan).toHaveBeenCalledTimes(1));
    expect(orchRunClient.confirmRun).not.toHaveBeenCalled();
  });

  it('needConfirm=true: updatePlan 失败 → confirmRun 不调用', async () => {
    const toastErrorSpy = vi.spyOn(toast, 'error').mockImplementation(() => '');
    vi.mocked(orchRunClient.updatePlan).mockRejectedValue(new Error('network down'));
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} needConfirm />);
    fireEvent.click(screen.getByTestId('plan-start'));
    await waitFor(() =>
      expect(toastErrorSpy).toHaveBeenCalledWith(expect.stringContaining('计划保存失败')),
    );
    expect(orchRunClient.confirmRun).not.toHaveBeenCalled();
    toastErrorSpy.mockRestore();
  });

  it('formats plan card as Markdown and JSON', () => {
    const md = formatPlanCardMarkdown('r-p91', plan, false, true);
    expect(md).toContain('# 编排计划 (r-p91)');
    expect(md).toContain('- 状态: 待编辑');
    expect(md).toContain('- **t1** [researcher]: G');
    const json = JSON.parse(formatPlanCardJson('r-p91', plan, false, true));
    expect(json.runId).toBe('r-p91');
    expect(json.needConfirm).toBe(true);
    expect(json.count).toBe(1);
  });
});

// ===== 编排计划卡片 UX (2026-10-26): reasoning 折叠 / 乐观折叠 / 自然语言修订 =====
describe('PlanCard 编排 UX (2026-10-26)', () => {
  const plan = [
    { task_id: 't1', agent_id: 'researcher', goal: 'G1' },
    { task_id: 't2', agent_id: 'writer', goal: 'G2' },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('reasoning 默认收起，点击 toggle 后展开', () => {
    render(
      <PlanCard
        runId="r1"
        plan={plan}
        locked={false}
        onCancel={() => {}}
        reasoning="先并行调研，再汇总成文"
      />,
    );
    expect(screen.queryByTestId('plan-reasoning')).toBeNull();
    fireEvent.click(screen.getByTestId('plan-reasoning-toggle'));
    expect(screen.getByTestId('plan-reasoning')).toHaveTextContent('先并行调研，再汇总成文');
  });

  it('无 reasoning 时不渲染规划思路区块', () => {
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} />);
    expect(screen.queryByTestId('plan-reasoning-toggle')).toBeNull();
  });

  it('开始执行成功 → 折叠成摘要；展开后回完整态（只读）', async () => {
    vi.mocked(orchRunClient.updatePlan).mockResolvedValue({ ok: true });
    vi.mocked(orchRunClient.confirmRun).mockResolvedValue({ ok: true });
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} needConfirm />);
    fireEvent.click(screen.getByTestId('plan-start'));
    await waitFor(() => expect(screen.getByTestId('plan-card-collapsed')).toBeInTheDocument());
    expect(screen.getByTestId('plan-card-collapsed')).toHaveTextContent(
      '编排计划已开始执行（2 项）',
    );
    expect(screen.queryByTestId('plan-card')).toBeNull();
    fireEvent.click(screen.getByTestId('plan-expand'));
    expect(screen.getByTestId('plan-card')).toBeInTheDocument();
    // 派发后后端 409 锁编辑 —— 展开态为纯只读
    expect(screen.getByTestId('plan-goal-t1')).toBeDisabled();
  });

  it('修订：未锁定渲染输入框，提交后透出用户输入并清空', async () => {
    const onRevise = vi.fn().mockResolvedValue(undefined);
    render(
      <PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} onRevise={onRevise} />,
    );
    const input = screen.getByTestId('plan-revise-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '把写作拆成两篇' } });
    fireEvent.click(screen.getByTestId('plan-revise-submit'));
    await waitFor(() => expect(onRevise).toHaveBeenCalledWith('把写作拆成两篇', plan));
    await waitFor(() => expect(input.value).toBe(''));
  });

  it('修订基线 = 本地 items（含未提交的 textarea 编辑），不是原始 plan prop', async () => {
    const onRevise = vi.fn().mockResolvedValue(undefined);
    render(
      <PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} onRevise={onRevise} />,
    );
    fireEvent.change(screen.getByTestId('plan-goal-t2'), { target: { value: '用户改过的目标' } });
    fireEvent.change(screen.getByTestId('plan-revise-input'), {
      target: { value: '给调研补一个摘要' },
    });
    fireEvent.click(screen.getByTestId('plan-revise-submit'));
    await waitFor(() => expect(onRevise).toHaveBeenCalledTimes(1));
    const [, currentItems] = onRevise.mock.calls[0];
    expect(currentItems).toEqual([
      { task_id: 't1', agent_id: 'researcher', goal: 'G1' },
      { task_id: 't2', agent_id: 'writer', goal: '用户改过的目标' },
    ]);
  });

  it('修订进行中 → 开始执行按钮禁用（两个 plan_json 写者互斥）', () => {
    render(
      <PlanCard
        runId="r1"
        plan={plan}
        locked={false}
        onCancel={() => {}}
        onRevise={vi.fn()}
        revising
      />,
    );
    expect(screen.getByTestId('plan-start')).toBeDisabled();
  });

  it('开始执行飞行中 → 修订被拒并 toast，不清空输入', async () => {
    const toastErrorSpy = vi.spyOn(toast, 'error').mockImplementation(() => '');
    // updatePlan 永不 resolve → startingRef 一直是 true（开始执行飞行中）
    vi.mocked(orchRunClient.updatePlan).mockReturnValue(new Promise(() => {}));
    const onRevise = vi.fn().mockResolvedValue(undefined);
    render(
      <PlanCard
        runId="r1"
        plan={plan}
        locked={false}
        onCancel={() => {}}
        onRevise={onRevise}
        needConfirm
      />,
    );
    fireEvent.click(screen.getByTestId('plan-start'));
    const input = screen.getByTestId('plan-revise-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '改一下' } });
    fireEvent.click(screen.getByTestId('plan-revise-submit'));
    await waitFor(() =>
      expect(toastErrorSpy).toHaveBeenCalledWith(expect.stringContaining('正在开始执行')),
    );
    expect(onRevise).not.toHaveBeenCalled();
    expect(input.value).toBe('改一下');
    toastErrorSpy.mockRestore();
  });

  it('修订：锁定后不渲染修订区块', () => {
    render(<PlanCard runId="r1" plan={plan} locked onCancel={() => {}} onRevise={vi.fn()} />);
    expect(screen.queryByTestId('plan-revise')).toBeNull();
  });

  it('修订失败 → toast + 保留输入', async () => {
    const toastErrorSpy = vi.spyOn(toast, 'error').mockImplementation(() => '');
    const onRevise = vi.fn().mockRejectedValue(new Error('llm down'));
    render(
      <PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} onRevise={onRevise} />,
    );
    const input = screen.getByTestId('plan-revise-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '改一下' } });
    fireEvent.click(screen.getByTestId('plan-revise-submit'));
    await waitFor(() =>
      expect(toastErrorSpy).toHaveBeenCalledWith(expect.stringContaining('计划修订失败')),
    );
    expect(input.value).toBe('改一下');
    toastErrorSpy.mockRestore();
  });

  it('plan prop 换引用（修订结果回写 store）→ 本地 items 同步', async () => {
    const { rerender } = render(
      <PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} />,
    );
    expect((screen.getByTestId('plan-goal-t1') as HTMLTextAreaElement).value).toBe('G1');
    rerender(
      <PlanCard
        runId="r1"
        plan={[
          { task_id: 't1', agent_id: 'researcher', goal: '修订后的目标' },
          { task_id: 't2', agent_id: 'writer', goal: 'G2' },
        ]}
        locked={false}
        onCancel={() => {}}
      />,
    );
    await waitFor(() =>
      expect((screen.getByTestId('plan-goal-t1') as HTMLTextAreaElement).value).toBe(
        '修订后的目标',
      ),
    );
  });
});
