import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { ExecutionModePicker, type ExecutionMode } from '../../components/ExecutionModePicker';
import { PlanCard } from '../../components/PlanCard';
import { ResearchSummaryCard } from '../../components/ResearchSummaryCard';
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
  /** 2026-10-28: Plan Mode 增强 — 执行模式推荐（由后端分类器返回） */
  recommendedExecutionMode?: 'single' | 'multi' | 'ask_user' | null;
  /** 2026-10-28: Plan Mode 增强 — 分类器判断依据（ask_user 时展示） */
  executionModeReasoning?: string;
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
  recommendedExecutionMode = null,
  executionModeReasoning,
}: PlanApprovalBarProps) {
  const planOrchBusyRef = useRef(false);
  const [revising, setRevising] = useState(false);
  const reviseBusyRef = useRef(false);

  // 2026-10-28: Plan Mode 增强 —— 执行模式智能推荐。
  // recommendedExecutionMode 来自后端分类器（single/multi/ask_user）；
  // modeOverride 是用户的显式覆盖，优先于推荐值。
  // 交互口径（计划文档 §3.1.2）：
  // - single/multi → 批准栏显示"推荐：X"，用户可下拉覆盖
  // - ask_user    → 自动弹出 ExecutionModePicker；用户取消 → 停止执行，
  //                 保留 plan 待审阅（不擅自选默认值）
  const [modeOverride, setModeOverride] = useState<ExecutionMode | null>(null);
  const [modePickerDismissed, setModePickerDismissed] = useState(false);

  // 新一轮推荐到达时重置"已忽略选择"标记与用户覆盖 —— 否则上一轮关掉的
  // 弹窗会让本轮的 ask_user 推荐静默失效，上一轮的模式覆盖也会污染新一轮。
  useEffect(() => {
    setModePickerDismissed(false);
    setModeOverride(null);
  }, [recommendedExecutionMode]);

  // 分类器的推荐（ask_user 不算推荐 —— 那表示"分类器没结论"）。
  const recommendedMode: ExecutionMode | null =
    recommendedExecutionMode === 'single' || recommendedExecutionMode === 'multi'
      ? recommendedExecutionMode
      : null;

  // 生效模式：用户覆盖 > 分类器推荐。ask_user 不算生效模式（需用户明确选）。
  const effectiveMode: ExecutionMode | null = modeOverride ?? recommendedMode;

  const showModePicker =
    recommendedExecutionMode === 'ask_user' && !modePickerDismissed && modeOverride === null;

  const modeLabel = (mode: ExecutionMode): string =>
    mode === 'single' ? '单 agent（串行）' : '编排模式（并行）';

  // 2026-10-28: Plan Mode 增强 Phase 2 —— 复杂任务深度调研结果。
  // researchReport 由 `research_complete` 事件写入 store，供 ResearchSummaryCard 渲染。
  // 必须用 selector 订阅而非 getState()：事件写入 store 时父组件 props 不变，
  // 非响应式读取会让调研卡片永远不出现（code review #13）。
  const researchReport = useChatStreamStore((s) =>
    currentSessionId && planApprovalFor === currentSessionId
      ? (s.sessions[currentSessionId]?.researchReport ?? null)
      : null,
  );

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

  // 2026-10-28: [基于调研生成 Plan] —— 把调研结论作为上下文重新进入
  // plan mode，让 planner 据此产出任务计划（不重新调研）。后端本轮会再次
  // 跑 preflight，但 scout 有缓存且复杂度不变，代价可接受。
  const handleGeneratePlanFromResearch = (): void => {
    if (!currentSessionId || !researchReport) return;
    const lines = [
      '请基于以下调研结论制定执行计划，不要重新调研。',
      `调研主题：${researchReport.topic}`,
      `预估工作量：${researchReport.estimated_effort}（充分度 ${Math.round(
        researchReport.confidence * 100,
      )}%）`,
    ];
    if (researchReport.findings.length > 0) {
      lines.push('关键发现：');
      for (const finding of researchReport.findings) {
        lines.push(`- ${finding.title}：${finding.summary}`);
      }
    }
    if (researchReport.synthesis) {
      lines.push('综合结论：', researchReport.synthesis);
    }
    useChatStreamStore.getState().setResearchReport(currentSessionId, null);
    void sendMessage(lines.join('\n'), currentSessionId, undefined, undefined, {
      planMode: true,
    });
  };

  // 2026-10-28: Plan Mode 增强 —— 批准动作按"生效模式"分派。
  // 主按钮尊重用户覆盖（effectiveMode）：multi → 走编排，否则单 agent 串行。
  // "（编排）"按钮始终走编排，作为不受推荐影响的显式入口。
  const approveAsSingle = (): void => {
    const sid = planApprovalFor;
    clearPlanApproval();
    if (sid) {
      void sendMessage('请严格按上述计划执行，不要重新规划。', sid, undefined, 'force_single');
    }
  };

  const approveAsOrchestration = (): void => {
    if (planOrchBusyRef.current) return;
    const sid = planApprovalFor;
    if (!sid) return;
    const planText = [...messages].reverse().find((m) => m.role === 'assistant')?.content ?? '';
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
  };

  const handleApprove = (): void => {
    if (effectiveMode === 'multi') {
      approveAsOrchestration();
      return;
    }
    approveAsSingle();
  };

  return (
    <>
      {planApprovalFor != null && planApprovalFor === currentSessionId && (
        <div className="px-4 pb-2" data-testid="plan-approval-bar">
          <div className="flex items-center justify-between gap-2 px-3 py-2 rounded border border-primary/40 bg-primary/5">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-xs text-text-secondary">
                计划已生成 —— 批准后将严格按上述计划执行
              </span>
              {recommendedMode && (
                <span
                  className="text-xs text-primary font-medium shrink-0"
                  data-testid="plan-recommended-mode"
                >
                  推荐：{modeLabel(recommendedMode)}
                </span>
              )}
              {recommendedMode && (
                <select
                  data-testid="plan-mode-select"
                  aria-label="执行模式"
                  className="text-xs rounded border border-border bg-bg px-1 py-0.5 shrink-0"
                  value={modeOverride ?? 'recommended'}
                  onChange={(e) => {
                    const v = e.target.value;
                    setModeOverride(v === 'recommended' ? null : (v as ExecutionMode));
                  }}
                >
                  <option value="recommended">按推荐执行</option>
                  <option value="single">强制单 agent</option>
                  <option value="multi">强制编排</option>
                </select>
              )}
              {recommendedExecutionMode === 'ask_user' && modePickerDismissed && (
                <>
                  <span
                    className="text-xs text-text-secondary shrink-0"
                    data-testid="plan-mode-pending"
                  >
                    执行模式待选择
                  </span>
                  <button
                    type="button"
                    data-testid="plan-mode-select-open"
                    className="text-xs rounded border border-primary text-primary px-1 py-0.5 shrink-0"
                    onClick={() => setModePickerDismissed(false)}
                  >
                    选择执行模式
                  </button>
                </>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                data-testid="plan-approve"
                disabled={recommendedExecutionMode === 'ask_user' && modeOverride === null}
                className={`px-2 py-1 text-xs rounded font-medium disabled:opacity-50 disabled:cursor-not-allowed ${
                  effectiveMode === 'single'
                    ? 'bg-primary text-bg-inv'
                    : 'bg-primary/20 text-primary border border-primary'
                }`}
                onClick={handleApprove}
              >
                按计划执行
              </button>
              <button
                type="button"
                data-testid="plan-approve-orch"
                disabled={recommendedExecutionMode === 'ask_user' && modeOverride === null}
                className={`px-2 py-1 text-xs rounded font-medium disabled:opacity-50 disabled:cursor-not-allowed ${
                  effectiveMode === 'multi'
                    ? 'bg-primary text-bg-inv'
                    : 'border border-primary text-primary'
                }`}
                title="将计划拆解为并行子任务卡，经 PlanCard 审阅后由子代理并行执行"
                onClick={approveAsOrchestration}
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
                : preflightPhase === 'complexity_classify'
                  ? '正在分析任务复杂度…'
                  : preflightPhase === 'execution_mode_classify'
                    ? '正在推荐执行模式…'
                    : '正在侦察收集事实…（随后生成任务计划）'}
            </span>
          </div>
        </div>
      )}
      {/* 2026-10-28 Plan Mode 增强 Phase 2: 复杂任务深度调研报告 */}
      {researchReport && (
        <div className="px-4 pb-2">
          <ResearchSummaryCard
            report={researchReport}
            onGeneratePlan={handleGeneratePlanFromResearch}
            onDismiss={() => {
              if (currentSessionId) {
                useChatStreamStore.getState().setResearchReport(currentSessionId, null);
              }
            }}
          />
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
      <ExecutionModePicker
        open={showModePicker}
        reasoning={executionModeReasoning}
        onSelect={(mode) => setModeOverride(mode)}
        onClose={() => setModePickerDismissed(true)}
      />
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
