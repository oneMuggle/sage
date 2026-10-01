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
