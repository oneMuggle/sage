import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { PlanCard } from '../../components/PlanCard';
import type { TaskBoardState } from '../../features/send-message/chatStreamStore';
import { useChatStreamStore } from '../../features/send-message/chatStreamStore';
import { orchRunClient } from '../../shared/api/orchRunClient';
import type { TaskPlanItem } from '../../shared/api/types';
import type { Message as MessageType } from '../../shared/lib/store';

export interface PlanApprovalBarProps {
  planApprovalFor: string | null;
  currentSessionId: string | null;
  clearPlanApproval: () => void;
  messages: MessageType[];
  sendMessage: (
    content: string,
    sessionId?: string,
    extraRefs?: unknown,
    orchestrateMode?: string,
    extraOptions?: Record<string, unknown>,
  ) => Promise<void>;
  preflightPhase: string | null;
  taskBoard: TaskBoardState | null;
  onCancelRun: (runId: string) => Promise<void>;
}

export function PlanApprovalBar({
  planApprovalFor,
  currentSessionId,
  clearPlanApproval,
  messages,
  sendMessage,
  preflightPhase,
  taskBoard,
  onCancelRun,
}: PlanApprovalBarProps) {
  const planOrchBusyRef = useRef(false);
  const [revising, setRevising] = useState(false);
  const reviseBusyRef = useRef(false);

  // 编排计划卡片 UX (2026-10-26): 自然语言修订（问题 3）—— 用户不必在
  // "开始执行 / 取消" 之间二选一。currentItems 由 PlanCard 传入，是用户在
  // textarea 里改过但尚未落库的计划；拿它（而不是 store 里的旧 plan）当
  // 修订基线，后端"未提及任务原样保留"才不会把用户的 goal 编辑还原掉。
  // current_plan 非空 → 后端走修订 prompt，只改用户提到的任务。
  const handleRevise = async (instruction: string, currentItems: TaskPlanItem[]) => {
    const board = taskBoard;
    if (!board) return;
    // 并发守卫：抛错而非静默 return —— PlanCard 的 catch 会 toast 并保留
    // 用户输入，静默 return 会让它误以为成功而清空 textarea。
    if (reviseBusyRef.current) {
      throw new Error('上一次计划修订仍在进行中，请稍候');
    }
    reviseBusyRef.current = true;
    setRevising(true);
    try {
      const { items, reasoning } = await orchRunClient.planItemsFromText(instruction, currentItems);
      if (items.length === 0) {
        throw new Error('LLM 未能根据修订说明生成任务');
      }
      // 修订 reasoning 为空时不覆盖库里有价值的原始规划思路。
      await orchRunClient.updatePlan(board.runId, items, reasoning || undefined);
      if (currentSessionId) {
        useChatStreamStore.getState().updateTaskBoard(currentSessionId, board.runId, (prev) =>
          prev
            ? {
                ...prev,
                plan: items,
                reasoning: reasoning || prev.reasoning,
                // task_progress 的 total 是修订前的旧值，而前端聚合只增不
                // 减 —— 5 项计划修订成 2 项后会一直显示"0/5"却只有 2 行。
                progress: prev.progress ? { ...prev.progress, total: items.length } : prev.progress,
              }
            : prev,
        );
      }
    } finally {
      reviseBusyRef.current = false;
      setRevising(false);
    }
  };

  return (
    <>
      {planApprovalFor != null && planApprovalFor === currentSessionId && (
        <div className="px-4 pb-2" data-testid="plan-approval-bar">
          <div className="flex items-center justify-between gap-2 px-3 py-2 rounded border border-primary/40 bg-primary/5">
            <span className="text-xs text-text-secondary">
              计划已生成 —— 批准后将严格按上述计划执行
            </span>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                data-testid="plan-approve"
                className="px-2 py-1 text-xs rounded bg-primary text-bg-inv font-medium"
                onClick={() => {
                  const sid = planApprovalFor;
                  clearPlanApproval();
                  if (sid) {
                    void sendMessage(
                      '请严格按上述计划执行，不要重新规划。',
                      sid,
                      undefined,
                      'force_single',
                    );
                  }
                }}
              >
                按计划执行
              </button>
              <button
                type="button"
                data-testid="plan-approve-orch"
                className="px-2 py-1 text-xs rounded border border-primary text-primary font-medium"
                title="将计划拆解为并行子任务卡，经 PlanCard 审阅后由子代理并行执行"
                onClick={() => {
                  if (planOrchBusyRef.current) return;
                  const sid = planApprovalFor;
                  if (!sid) return;
                  const planText =
                    [...messages].reverse().find((m) => m.role === 'assistant')?.content ?? '';
                  if (!planText.trim()) {
                    toast.error('找不到可结构化的计划内容');
                    return;
                  }
                  planOrchBusyRef.current = true;
                  orchRunClient
                    .planItemsFromText(planText)
                    .then(({ items }) => {
                      clearPlanApproval();
                      if (items.length > 0) {
                        void sendMessage(
                          '请按上述已批准的计划编排执行（已生成任务卡，确认后并行执行）。',
                          sid,
                          undefined,
                          undefined,
                          { planOverride: items },
                        );
                      } else {
                        toast.error('未能从计划解析出任务，请改用「按计划执行」');
                      }
                    })
                    .catch((err: unknown) => {
                      toast.error(
                        err instanceof Error
                          ? `计划转编排失败：${err.message.slice(0, 120)}`
                          : '计划转编排失败（需要已配置 LLM 端点）',
                      );
                    })
                    .finally(() => {
                      planOrchBusyRef.current = false;
                    });
                }}
              >
                按计划执行（编排）
              </button>
              <button
                type="button"
                data-testid="plan-dismiss"
                className="px-2 py-1 text-xs rounded border border-border text-text-secondary"
                onClick={() => clearPlanApproval()}
              >
                忽略
              </button>
            </div>
          </div>
        </div>
      )}
      {preflightPhase && !taskBoard && (
        <div className="px-4 pb-2" data-testid="orch-preflight-indicator">
          <div className="flex items-center gap-2 px-3 py-2 rounded border border-border bg-bg-muted/40">
            <span className="text-xs text-text-secondary animate-pulse">
              {preflightPhase === 'clarify'
                ? '正在澄清需求…（如在输入框中回答提问，将据此生成更准的计划）'
                : '正在侦察收集事实…（随后生成任务计划）'}
            </span>
          </div>
        </div>
      )}
      {taskBoard && !taskBoard.dispatchedAt && (
        <div className="px-4 pb-2">
          <PlanCard
            runId={taskBoard.runId}
            plan={taskBoard.plan}
            locked={false}
            needConfirm={true}
            reasoning={taskBoard.reasoning}
            onRevise={(instruction, currentItems) => handleRevise(instruction, currentItems)}
            revising={revising}
            onCancel={() => void onCancelRun(taskBoard.runId)}
          />
        </div>
      )}
    </>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditPlanApprovalBarGovernance(
  state: {
    stepCount?: number;
    approvalState?: 'pending' | 'approved' | 'rejected' | string;
    canEditPlan?: boolean;
  } = {},
): {
  module: 'src/pages/chat/PlanApprovalBar.tsx';
  phase: 'P142';
  stepCount: number;
  approvalState: 'pending' | 'approved' | 'rejected';
  canEditPlan: boolean;
  healthy: boolean;
} {
  const stepCount =
    typeof state.stepCount === 'number' && Number.isFinite(state.stepCount)
      ? Math.max(0, Math.trunc(state.stepCount))
      : 3;
  const approvalState =
    state.approvalState === 'approved' || state.approvalState === 'rejected'
      ? state.approvalState
      : 'pending';
  const canEditPlan = state.canEditPlan !== false;
  return {
    module: 'src/pages/chat/PlanApprovalBar.tsx',
    phase: 'P142',
    stepCount,
    approvalState,
    canEditPlan,
    healthy: stepCount >= 0,
  };
}
