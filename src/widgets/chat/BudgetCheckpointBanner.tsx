// src/widgets/chat/BudgetCheckpointBanner.tsx
//
// 2026-11-05 M5（迭代预算可见性配套）：
// 后端在动态预算模式下依据进度审计自动延长迭代上限时，会推送
// `state: 'iteration_checkpoint'` 事件。此前前端只 toast 3 秒即消失，
// 用户很容易错过"预算已被延长"的事实。本组件把它渲染为会话级持久横幅，
// 接入 ChatNoticeStack 与其他会话提示统一排版。
//
// 生命周期：run 期间常驻（由 chatStreamStore.budgetCheckpoint 驱动），
// run 收尾（clearStream）或用户点击关闭时消失。

import type { BudgetCheckpointInfo } from '../../features/send-message/chatStreamStore';

interface BudgetCheckpointBannerProps {
  info: BudgetCheckpointInfo;
  onDismiss: () => void;
}

export function BudgetCheckpointBanner({ info, onDismiss }: BudgetCheckpointBannerProps) {
  const { extensions, nextBudget, previousBudget } = info;
  const range =
    previousBudget != null && previousBudget > 0
      ? `${previousBudget} → ${nextBudget}`
      : `${nextBudget}`;

  return (
    <div
      data-testid="budget-checkpoint-banner"
      className="flex items-center gap-2 px-5 py-2 bg-info/10 border-b border-border text-xs shrink-0"
    >
      <span className="text-info shrink-0">
        已自动延长迭代预算（第 {extensions} 次，当前上限 {range} 步）
      </span>
      <button
        className="ml-auto text-text-secondary hover:text-text shrink-0"
        aria-label="关闭预算延长提示"
        data-testid="budget-checkpoint-dismiss"
        onClick={onDismiss}
      >
        ×
      </button>
    </div>
  );
}
