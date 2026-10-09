import { useRef } from 'react';
import { toast } from 'sonner';

import { PlanCard } from '../../components/PlanCard';
import type { TaskBoardState } from '../../features/send-message/chatStreamStore';
import { orchRunClient } from '../../shared/api/orchRunClient';
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
            onCancel={() => void onCancelRun(taskBoard.runId)}
          />
        </div>
      )}
    </>
  );
}
