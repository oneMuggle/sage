// src/widgets/chat/InterruptedRunBanner.tsx
//
// L16 run 级崩溃恢复 (对标增强第四轮批次 A): 后端启动时把滞留 running 的
// 会话统一标记 failed("应用重启，运行中断",backend/data/session_repo.py
// recover_stale_run_states)。本横幅是该终态在聊天页的恢复入口——
// 重发最后一条 user 消息,而不是让用户对着侧栏灰点猜。

/** 与后端 session_repo.recover_stale_run_states 的恢复文案严格一致 */
export const INTERRUPTED_RUN_ERROR = '应用重启，运行中断';

interface InterruptedRunBannerProps {
  onRetry: () => void;
  onDismiss: () => void;
}

export function InterruptedRunBanner({ onRetry, onDismiss }: InterruptedRunBannerProps) {
  return (
    <div
      data-testid="interrupted-run-banner"
      className="flex items-center gap-2 px-5 py-2 bg-warning/10 border-b border-border text-xs shrink-0"
    >
      <span className="text-warning shrink-0">上次运行被应用重启中断</span>
      <button
        onClick={onRetry}
        className="px-2 py-0.5 border border-border rounded-radius-sm hover:bg-bg-hover transition-colors"
      >
        重发最后一条消息
      </button>
      <button
        className="ml-auto text-text-secondary hover:text-text"
        aria-label="忽略中断提示"
        onClick={onDismiss}
      >
        忽略
      </button>
    </div>
  );
}
