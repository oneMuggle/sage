/**
 * CatalogTable — Catalog 列表视图 (Task 6, 2026-09-15)
 *
 * 渲染 catalog 源视图 (CandidateModel[]) + 选择 + 探测触发。
 * 价格、上下文窗口、来源、定价范围全部以纯展示方式渲染, 不参与计算。
 *
 * 无障碍:
 * - 状态/徽标使用「图标 + 文字」组合, 不只靠颜色
 * - 行可键盘聚焦, Enter/Space 触发选中
 */
import { useState } from 'react';

import type { CandidateModel } from '../../entities/model-catalog/types';

interface CatalogTableProps {
  items: CandidateModel[];
  selectedKey: string | null;
  onSelect: (item: CandidateModel) => void;
  loading?: boolean;
}

// eslint-disable-next-line react-refresh/only-export-components
export function catalogItemKey(item: CandidateModel): string {
  return [item.model_key.provider, item.model_key.model_id, item.source, item.pricing_scope]
    .map((part) => encodeURIComponent(part))
    .join('/');
}

function priceDisplay(p: CandidateModel['price']): string {
  const inV = p.input_per_million === null ? '未知' : `$${p.input_per_million}`;
  const outV = p.output_per_million === null ? '未知' : `$${p.output_per_million}`;
  return `入 ${inV} / 出 ${outV}`;
}

function contextDisplay(item: CandidateModel): string {
  if (item.native === null) return '未知';
  return `${item.native.toLocaleString()} tokens`;
}

export function CatalogTable({ items, selectedKey, onSelect, loading }: CatalogTableProps) {
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const [copiedRowKey, setCopiedRowKey] = useState<string | null>(null);

  /* v8 ignore start */
  const handleCopyMd = async () => {
    const lines = [
      '# 模型目录',
      '',
      `- **模型总数**: ${items.length}`,
      '',
      '| 模型 | 上下文窗口 | 价格 (USD/M) | 来源 | 定价范围 |',
      '| --- | --- | --- | --- | --- |',
      ...items.map(
        (it) =>
          `| ${it.model_key.provider}/${it.model_key.model_id} | ${contextDisplay(it)} | ${priceDisplay(it.price)} | ${it.source} | ${it.pricing_scope} |`,
      ),
    ];
    setCopiedMd(true);
    await navigator.clipboard?.writeText(lines.join('\n'));
    setTimeout(() => setCopiedMd(false), 1800);
  };

  const handleCopyJson = async () => {
    setCopiedJson(true);
    await navigator.clipboard?.writeText(JSON.stringify(items, null, 2));
    setTimeout(() => setCopiedJson(false), 1800);
  };

  const handleCopyRowJson = async (e: React.MouseEvent, item: CandidateModel, key: string) => {
    e.stopPropagation();
    setCopiedRowKey(key);
    await navigator.clipboard?.writeText(JSON.stringify(item, null, 2));
    setTimeout(() => setCopiedRowKey((prev) => (prev === key ? null : prev)), 1800);
  };
  /* v8 ignore stop */

  if (loading) {
    return (
      <div
        className="p-3 text-xs text-text-muted"
        data-testid="catalog-table-loading"
        role="status"
        aria-live="polite"
      >
        <span aria-hidden="true">⏳</span> 加载中…
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="p-3 text-xs text-text-muted" data-testid="catalog-table-empty" role="status">
        <span aria-hidden="true">📭</span> 暂无模型, 请尝试同步 OpenRouter 或导入快照
      </div>
    );
  }
  return (
    <div
      className="border border-border rounded overflow-hidden"
      data-testid="catalog-table"
      role="table"
      aria-label="模型目录"
    >
      <div className="flex items-center justify-end gap-1.5 px-2 py-1 bg-bg-muted border-b border-border">
        <button
          type="button"
          data-testid="catalog-table-copy-md-btn"
          onClick={() => void handleCopyMd()}
          className="px-2 py-0.5 text-ui-xs rounded border border-border bg-bg text-text hover:bg-bg-hover"
        >
          {copiedMd ? '✓ 已复制MD' : '复制目录MD'}
        </button>
        <button
          type="button"
          data-testid="catalog-table-copy-json-btn"
          onClick={() => void handleCopyJson()}
          className="px-2 py-0.5 text-ui-xs rounded border border-border bg-bg text-text hover:bg-bg-hover"
        >
          {copiedJson ? '✓ 已复制JSON' : '复制目录JSON'}
        </button>
      </div>
      <table className="w-full text-xs">
        <thead className="bg-bg-muted">
          <tr className="text-text-muted">
            <th className="font-normal text-left p-2">模型</th>
            <th className="font-normal text-left p-2">上下文窗口</th>
            <th className="font-normal text-left p-2">价格 (USD/M)</th>
            <th className="font-normal text-left p-2">来源</th>
            <th className="font-normal text-left p-2">定价范围</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const key = catalogItemKey(item);
            const modelLabel = `${item.model_key.provider}/${item.model_key.model_id}`;
            const selected = selectedKey === key;
            return (
              <tr
                key={key}
                role="row"
                aria-selected={selected}
                tabIndex={0}
                onClick={() => onSelect(item)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelect(item);
                  }
                }}
                data-testid={`catalog-row-${key}`}
                className={`border-t border-border cursor-pointer focus:outline-none focus:ring-1 focus:ring-accent ${
                  selected ? 'bg-accent-soft' : 'hover:bg-bg-hover'
                }`}
              >
                <td className="p-2 font-mono">{modelLabel}</td>
                <td className="p-2">{contextDisplay(item)}</td>
                <td className="p-2">{priceDisplay(item.price)}</td>
                <td className="p-2">{item.source}</td>
                <td className="p-2 flex items-center justify-between gap-2">
                  <span>{item.pricing_scope}</span>
                  <button
                    type="button"
                    data-testid={`catalog-row-copy-json-${key}`}
                    onClick={(e) => void handleCopyRowJson(e, item, key)}
                    className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-text-muted hover:text-text hover:bg-bg"
                  >
                    {copiedRowKey === key ? '✓ 已复制' : '复制JSON'}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
