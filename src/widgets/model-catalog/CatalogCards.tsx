/**
 * CatalogCards — 模型目录卡片视图 (Task 10, 2026-10-28)
 *
 * 与 CatalogTable 同形 props, 页面在两个视图间共享同一份 filteredItems。
 * 卡片展示 candidate tier (R18), 不逐模型请求 effective。
 *
 * 无障碍:
 * - 卡片可键盘聚焦, Enter/Space 触发选中 (与表格行同契约)
 * - 选中态同时用 aria-selected 和左侧 accent 边框表达, 不只靠颜色
 */
import type { CandidateModel } from '../../entities/model-catalog/types';

import { catalogItemKey } from './CatalogTable';

interface CatalogCardsProps {
  items: CandidateModel[];
  selectedKey: string | null;
  onSelect: (item: CandidateModel) => void;
  loading?: boolean;
}

/** 分档中文标签 — 页面过滤下拉共用。 */
// eslint-disable-next-line react-refresh/only-export-components
export const TIER_LABELS: Record<'fast' | 'balanced' | 'powerful' | 'unknown', string> = {
  fast: '快速',
  balanced: '均衡',
  powerful: '强力',
  unknown: '未知',
};

/** 能力中文标签 — 页面过滤下拉共用; 未收录的能力原样展示。 */
// eslint-disable-next-line react-refresh/only-export-components
export const CAPABILITY_LABELS: Record<string, string> = {
  vision: '视觉',
  tool_use: '工具',
  json: 'JSON',
  reasoning: '推理',
};

function tierLabel(tier: string | null | undefined): string {
  if (tier === 'fast' || tier === 'balanced' || tier === 'powerful') {
    return TIER_LABELS[tier];
  }
  return TIER_LABELS.unknown;
}

function priceDisplay(price: CandidateModel['price']): string {
  const inV = price.input_per_million === null ? '未知' : `$${price.input_per_million}`;
  const outV = price.output_per_million === null ? '未知' : `$${price.output_per_million}`;
  return `入 ${inV} / 出 ${outV}`;
}

function contextDisplay(item: CandidateModel): string {
  if (item.native === null) return '未知';
  return `${item.native.toLocaleString()} tokens`;
}

export function CatalogCards({ items, selectedKey, onSelect, loading }: CatalogCardsProps) {
  if (loading) {
    return (
      <div
        className="p-3 text-xs text-text-muted"
        data-testid="catalog-cards-loading"
        role="status"
        aria-live="polite"
      >
        <span aria-hidden="true">⏳</span> 加载中…
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="p-3 text-xs text-text-muted" data-testid="catalog-cards-empty" role="status">
        <span aria-hidden="true">📭</span> 暂无模型, 请尝试同步 OpenRouter 或导入快照
      </div>
    );
  }
  return (
    <div
      className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(260px,1fr))]"
      data-testid="catalog-cards"
      role="list"
      aria-label="模型目录"
    >
      {items.map((item) => {
        const key = catalogItemKey(item);
        const selected = selectedKey === key;
        const capabilities = Object.entries(item.capabilities ?? {})
          .filter(([, supported]) => supported === true)
          .map(([name]) => ({ name, label: CAPABILITY_LABELS[name] ?? name }));
        return (
          <div
            key={key}
            role="listitem"
            tabIndex={0}
            aria-selected={selected}
            onClick={() => onSelect(item)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelect(item);
              }
            }}
            data-testid={`catalog-card-${key}`}
            className={`flex flex-col gap-2 rounded border border-l-2 border-border p-3 cursor-pointer focus:outline-none focus:ring-1 focus:ring-accent ${
              selected ? 'bg-accent-soft border-l-accent' : 'border-l-transparent hover:bg-bg-hover'
            }`}
          >
            <div className="font-mono text-xs break-all">
              {item.model_key.provider}/{item.model_key.model_id}
            </div>
            <div className="flex flex-wrap items-center gap-1">
              <span
                className="rounded border border-border bg-bg-muted px-1.5 py-0.5 text-xs"
                data-testid="catalog-card-tier"
              >
                {tierLabel(item.tier)}
              </span>
              {capabilities.length === 0 ? (
                <span className="text-xs text-text-muted">能力未知</span>
              ) : (
                capabilities.map((cap) => (
                  <span
                    key={cap.name}
                    className="rounded border border-border px-1.5 py-0.5 text-xs text-text-secondary"
                    data-testid={`catalog-card-capability-${cap.name}`}
                  >
                    {cap.label}
                  </span>
                ))
              )}
            </div>
            <div className="text-xs">
              <span className="text-text-muted">原生上下文 </span>
              {contextDisplay(item)}
            </div>
            <div className="text-xs">
              <span className="text-text-muted">价格 </span>
              {priceDisplay(item.price)}
            </div>
            <div className="text-xs text-text-muted">
              {item.source} · {item.pricing_scope}
            </div>
          </div>
        );
      })}
    </div>
  );
}
