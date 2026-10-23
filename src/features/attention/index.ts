// 批次 D 数据层。类型暂不从 barrel 再导出：UI 消费方（rail 角标 / 汇总气泡）
// 属批次 B/D 的接线范围，还未落地；预先导出会成为 knip 新增违规
// （基线棘轮只增不减）。届时随首个消费方一起放开。
export {
  aggregateAttention,
  attentionSummary,
  attentionTitle,
  emptyAttentionSnapshot,
  ATTENTION_KINDS,
} from './attentionCenter';
export { countDirtyFiles, countPendingTodos, useAttentionSnapshot } from './useAttentionSnapshot';
import { ATTENTION_KINDS as _ATTENTION_KINDS } from './attentionCenter';

export function formatAttentionBarrelSummary(): string {
  return `module=features/attention · kinds=${_ATTENTION_KINDS.length} · exports=8`;
}

export function formatAttentionBarrelJson(): string {
  return JSON.stringify({
    module: 'features/attention',
    kinds: [..._ATTENTION_KINDS],
    exportCount: 8,
  });
}

export function auditAttentionBarrelGovernance(
  state: {
    exportedCount?: number;
  } = {},
): {
  module: 'src/features/attention/index.ts';
  phase: 'P158';
  exportedCount: number;
  healthy: boolean;
} {
  const exportedCount =
    typeof state.exportedCount === 'number' && Number.isFinite(state.exportedCount)
      ? Math.max(0, Math.trunc(state.exportedCount))
      : 8;
  return {
    module: 'src/features/attention/index.ts',
    phase: 'P158',
    exportedCount,
    healthy: exportedCount >= 5,
  };
}
