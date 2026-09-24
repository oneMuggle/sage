/**
 * TM2 (DSH 对标 R11): 上下文水位徽章 —— 随 context_pressure 流事件更新。
 *
 * 默认安静：< 0.6 不渲染；≥ 0.6 琥珀提示；≥ 0.8 红色警示
 * （deepseek-harness Web UI 同款语义：pressure 对用户可见，透明可控）。
 */
import { useStore } from '../../../shared/lib/store';

const AMBER_THRESHOLD = 0.6;
const RED_THRESHOLD = 0.8;

export function ContextPressureBadge({ sessionId }: { sessionId: string | null }) {
  const contextPressure = useStore((s) => s.contextPressure);

  if (!contextPressure || contextPressure.session_id !== sessionId) return null;
  const { pressure, total_tokens, budget_tokens } = contextPressure;
  if (pressure < AMBER_THRESHOLD) return null;

  const isRed = pressure >= RED_THRESHOLD;
  const percent = Math.round(pressure * 100);
  const label = isRed
    ? `⚠ ${percent}% · ${total_tokens}/${budget_tokens}`
    : `${percent}% · ${total_tokens}/${budget_tokens}`;

  return (
    <div
      data-testid="context-pressure-badge"
      role="status"
      className={
        isRed
          ? 'mb-1 rounded-md bg-red-500/15 px-2 py-1 text-xs text-red-600 dark:text-red-400'
          : 'mb-1 rounded-md bg-amber-500/15 px-2 py-1 text-xs text-amber-600 dark:text-amber-400'
      }
    >
      {label}
    </div>
  );
}
