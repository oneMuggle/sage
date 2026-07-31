import { CheckCircle2, Circle, ListChecks, Loader2, XCircle } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import type { ToolChainSnapshot, ToolStepSnapshot } from '../../shared/api';
import { formatStepDuration } from '../../shared/lib/utils';

interface ToolChainWidgetProps {
  /** 当前 run 的工具链快照（null = 无活跃工具链） */
  chain: ToolChainSnapshot | null;
}

/** 流结束后保持显示的淡出延迟（毫秒） */
const FADE_OUT_DELAY_MS = 2500;
/** 淡出动画时长（毫秒，与 transition-opacity duration-300 对齐） */
const FADE_OUT_ANIMATION_MS = 300;

/** 参数预览：单行截断，供 tooltip 与行内摘要。 */
function formatArgsPreview(args: Record<string, unknown>): string {
  const parts = Object.entries(args).map(([k, v]) => {
    const s = typeof v === 'string' ? v : JSON.stringify(v);
    return `${k}=${s.length > 30 ? `${s.slice(0, 30)}…` : s}`;
  });
  return parts.join(' ');
}

const STEP_ICON: Record<
  ToolStepSnapshot['status'],
  React.ComponentType<{ className?: string }>
> = {
  pending: Circle,
  running: Loader2,
  done: CheckCircle2,
  error: XCircle,
};

const STEP_ICON_CLASS: Record<ToolStepSnapshot['status'], string> = {
  pending: 'text-muted',
  running: 'text-primary animate-spin',
  done: 'text-success',
  error: 'text-error',
};

/**
 * A19 Tool Chain Tracking — 工具链实时进度侧栏组件。
 *
 * 渲染当前 run 的工具调用序列：每步显示状态图标、工具名、耗时与结果摘要，
 * 顶部显示总体进度条。数据来源是 useChat 暴露的 toolChain 快照
 * （后端 tool_chain_update 流事件，backend/domain/tool_chain.py）。
 *
 * 行为：chain 非空且有步骤时淡入；chain 归空后延迟淡出（避免流结束瞬间
 * 面板突然消失），与 ActiveAgentIndicator 的淡出模式一致。
 */
export function ToolChainWidget({ chain }: ToolChainWidgetProps) {
  const [visible, setVisible] = useState(false);
  // 淡出期间保留最后一帧快照，避免面板内容先清空再消失
  const [lastChain, setLastChain] = useState<ToolChainSnapshot | null>(null);
  const timersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

  useEffect(() => {
    const timers = timersRef.current;
    if (chain && chain.steps.length > 0) {
      timers.forEach((t) => clearTimeout(t));
      timers.clear();
      setLastChain(chain);
      setVisible(true);
    } else {
      const outer = setTimeout(() => {
        timers.delete(outer);
        setVisible(false);
        const inner = setTimeout(() => {
          timers.delete(inner);
          setLastChain(null);
        }, FADE_OUT_ANIMATION_MS);
        timers.add(inner);
      }, FADE_OUT_DELAY_MS);
      timers.add(outer);
    }
    return () => {
      timers.forEach((t) => clearTimeout(t));
      timers.clear();
    };
  }, [chain]);

  const display = chain ?? lastChain;
  if (!display || display.steps.length === 0) {
    return null;
  }

  const percent = Math.round(display.progress * 100);

  return (
    <aside
      data-testid="tool-chain-widget"
      aria-label="工具链执行进度"
      aria-live="polite"
      className={`absolute bottom-2 right-2 z-10 w-72 max-w-[calc(100%-1rem)] border border-border rounded-radius-sm bg-surface shadow-lg transition-opacity duration-300 ${
        visible ? 'opacity-100' : 'opacity-0 pointer-events-none'
      }`}
    >
      {/* 头部：标题 + 进度统计 */}
      <div className="flex items-center justify-between px-3 pt-2 pb-1.5 border-b border-border">
        <span className="flex items-center gap-1.5 text-xs font-medium text-text">
          <ListChecks className="w-3.5 h-3.5 text-primary" />
          工具链进度
        </span>
        <span className="text-xs text-muted tabular-nums">
          {display.completed_steps}/{display.total_steps} · {percent}%
        </span>
      </div>

      {/* 进度条 */}
      <div
        className="h-1 bg-border"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full bg-primary transition-all duration-300"
          style={{ width: `${percent}%` }}
        />
      </div>

      {/* 步骤列表 */}
      <ul className="max-h-44 overflow-y-auto py-1">
        {display.steps.map((step) => {
          const Icon = STEP_ICON[step.status];
          const argsPreview = formatArgsPreview(step.args);
          return (
            <li
              key={step.step_id}
              data-testid={`tool-step-${step.step_id}`}
              data-status={step.status}
              className="flex items-start gap-2 px-3 py-1 text-xs"
            >
              <Icon className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${STEP_ICON_CLASS[step.status]}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-mono font-medium text-text truncate">
                    {step.tool_name}
                  </span>
                  <span className="text-muted tabular-nums flex-shrink-0">
                    {formatStepDuration(step.duration_ms)}
                  </span>
                </div>
                {argsPreview && (
                  <div className="text-muted truncate" title={argsPreview}>
                    {argsPreview}
                  </div>
                )}
                {step.status === 'error' && step.error_message && (
                  <div className="text-error truncate" title={step.error_message}>
                    {step.error_message}
                  </div>
                )}
                {step.status === 'done' && step.result && (
                  <div className="text-muted truncate" title={step.result}>
                    {step.result}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
