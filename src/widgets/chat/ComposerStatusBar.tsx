// src/widgets/chat/ComposerStatusBar.tsx
//
// 2026-11-25: 输入框下方的会话状态条 (对标 ChatGPT / Claude / Cursor 的
// composer footer)。把原先占据顶栏的「用量统计 / 响应速度统计 / 上下文统计」
// 三块观测指标下沉到输入卡页脚，与空会话时的引导语互斥（同一插槽，二选一）。
//
// 布局: 左侧 = 用量徽章 (token / 成本 / 缓存命中率 / 平均响应时间)，
//      右侧 = 上下文占用条；两者的明细都在点击后向上展开的弹层里。

import { ContextMeter } from './ContextMeter';
import { SessionUsageBadge } from './SessionUsageBadge';
import { useSessionUsage } from './hooks/useSessionUsage';

interface ComposerStatusBarProps {
  /** 当前会话 id；null 表示还没有会话（此时不取数、不渲染）。 */
  sessionId: string | null;
}

export function ComposerStatusBar({ sessionId }: ComposerStatusBarProps) {
  const { usage } = useSessionUsage(sessionId);

  if (!usage) return null;

  // 用量徽章需要至少一次请求；上下文条需要上一轮的 prompt 快照。
  const showUsage = usage.requests > 0;
  const showContext = usage.last_prompt_tokens != null;
  if (!showUsage && !showContext) return null;

  return (
    <div
      className="flex min-w-0 flex-1 items-center justify-between gap-2"
      data-testid="composer-status-bar"
    >
      <div className="flex min-w-0 items-center gap-2">
        {showUsage && <SessionUsageBadge usage={usage} />}
      </div>
      {showContext && <ContextMeter usage={usage} placement="top" align="right" />}
    </div>
  );
}
