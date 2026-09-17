/**
 * SnapshotReview — 字段级 diff 审核组件 (Task 6, 2026-09-15)
 *
 * 设计要点 (对照 brief §「审核展示逐字段来源/旧值/新值/保护状态」):
 * - 每行展示 per-field source / old / new / protected 四列
 * - 用户必须显式勾选才能 apply (按钮初始 enabled — 等待字段勾选后端检查)
 * - 409 (stale revision) → 重拉 diff + 弹"已被修改, 请重确认"
 * - 状态由"图标 + 文字"传达 (不依赖颜色, 满足 WCAG 1.4.1)
 * - 键盘可操作: Tab 走流程, Enter 确认, Esc 取消
 * - 提交期间按钮 disabled 防双击
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { apply as applyApi, getDiff, ignore as ignoreApi } from '../../entities/model-catalog/api';
import {
  FIELD_LABELS,
  type ReviewableField,
  REVIEWABLE_FIELDS,
  type SnapshotDiff as SnapshotDiffItem,
} from '../../entities/model-catalog/types';

interface SnapshotReviewProps {
  snapshotId: string;
  /** 关闭回调 (Esc 或「关闭」按钮) */
  onClose?: () => void;
}

/** 字段值格式化 — null 显示「未知」, 价格保持字符串原样 */
function formatFieldValue(field: ReviewableField, value: unknown): string {
  if (value === null || value === undefined) return '未知';
  if (field === 'price') {
    const p = value as { input_per_million?: string | null; output_per_million?: string | null };
    const inV =
      p.input_per_million === null || p.input_per_million === undefined
        ? '未知'
        : `$${p.input_per_million}`;
    const outV =
      p.output_per_million === null || p.output_per_million === undefined
        ? '未知'
        : `$${p.output_per_million}`;
    return `入 ${inV} / 出 ${outV} (USD/M)`;
  }
  if (field === 'native') {
    return typeof value === 'number' ? `${value.toLocaleString()} tokens` : String(value);
  }
  if (field === 'capabilities') {
    const caps = value as Record<string, boolean>;
    const on = Object.keys(caps).filter((k) => caps[k]);
    return on.length === 0 ? '—' : on.join(', ');
  }
  return String(value);
}

export function SnapshotReview({ snapshotId, onClose }: SnapshotReviewProps) {
  const [items, setItems] = useState<SnapshotDiffItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFields, setSelectedFields] = useState<Record<string, Set<ReviewableField>>>({});
  const [submitting, setSubmitting] = useState(false);
  const [statusBanner, setStatusBanner] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const reloadGeneration = useRef(0);
  const snapshotIdRef = useRef(snapshotId);
  snapshotIdRef.current = snapshotId;
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    if (snapshotIdRef.current !== snapshotId) return;
    const generation = ++reloadGeneration.current;
    setLoading(true);
    setError(null);
    try {
      const data = await getDiff(snapshotId);
      if (
        !mountedRef.current ||
        snapshotIdRef.current !== snapshotId ||
        generation !== reloadGeneration.current
      )
        return;
      setItems(data);
      // 默认勾选 classification 为 new / updated 的项的全部字段
      const defaults: Record<string, Set<ReviewableField>> = {};
      for (const item of data) {
        if (
          item.status === 'pending' &&
          (item.classification === 'new' || item.classification === 'updated')
        ) {
          defaults[item.id] = new Set(REVIEWABLE_FIELDS);
        }
      }
      setSelectedFields(defaults);
    } catch (err) {
      if (
        !mountedRef.current ||
        snapshotIdRef.current !== snapshotId ||
        generation !== reloadGeneration.current
      )
        return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (
        mountedRef.current &&
        snapshotIdRef.current === snapshotId &&
        generation === reloadGeneration.current
      )
        setLoading(false);
    }
  }, [snapshotId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Esc 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && onClose) {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  function toggle(itemId: string, field: ReviewableField): void {
    setSelectedFields((prev) => {
      const existing = new Set(prev[itemId] ?? []);
      if (existing.has(field)) {
        existing.delete(field);
      } else {
        existing.add(field);
      }
      return { ...prev, [itemId]: existing };
    });
  }

  async function handleApply(item: SnapshotDiffItem): Promise<void> {
    const fields = Array.from(selectedFields[item.id] ?? new Set());
    if (fields.length === 0) {
      setStatusBanner('请至少勾选一个字段');
      return;
    }
    setSubmitting(true);
    setStatusBanner(null);
    try {
      await applyApi(snapshotId, item.id, fields, item.base_revision);
      if (!mountedRef.current) return;
      setStatusBanner(`已应用: ${item.after.model_key.model_id}`);
      await reload();
    } catch (err) {
      if (!mountedRef.current) return;
      const msg = err instanceof Error ? err.message : String(err);
      if (/409|HTTP\s+409/.test(msg)) {
        setStatusBanner('快照已被修改, 请重新审核');
        await reload();
      } else {
        setStatusBanner(`应用失败: ${msg}`);
      }
    } finally {
      if (mountedRef.current) setSubmitting(false);
    }
  }

  async function handleIgnore(item: SnapshotDiffItem): Promise<void> {
    setSubmitting(true);
    setStatusBanner(null);
    try {
      await ignoreApi(snapshotId, item.id);
      if (!mountedRef.current) return;
      setStatusBanner(`已忽略: ${item.after.model_key.model_id}`);
      await reload();
    } catch (err) {
      if (!mountedRef.current) return;
      const msg = err instanceof Error ? err.message : String(err);
      setStatusBanner(`忽略失败: ${msg}`);
    } finally {
      if (mountedRef.current) setSubmitting(false);
    }
  }

  if (loading && items.length === 0) {
    return (
      <div
        className="space-y-3 p-4 border border-border rounded-md bg-bg-muted"
        data-testid="snapshot-review"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text">
            <span aria-hidden="true">📋</span> 快照审核 · {snapshotId}
          </h3>
          <button
            type="button"
            data-testid="snapshot-review-apply-all"
            disabled
            aria-label="应用所选字段"
            className="px-3 py-1.5 text-xs border border-border rounded text-text bg-bg hover:bg-bg-hover disabled:opacity-50"
          >
            应用所选字段
          </button>
        </div>
        <div className="p-4 text-xs text-muted" data-testid="snapshot-review-loading">
          加载差异…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="space-y-3 p-4 border border-border rounded-md bg-bg-muted"
        data-testid="snapshot-review"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text">
            <span aria-hidden="true">📋</span> 快照审核 · {snapshotId}
          </h3>
          <button
            type="button"
            data-testid="snapshot-review-apply-all"
            disabled
            aria-label="应用所选字段"
            className="px-3 py-1.5 text-xs border border-border rounded text-text bg-bg hover:bg-bg-hover disabled:opacity-50"
          >
            应用所选字段
          </button>
        </div>
        <div
          className="p-4 text-xs"
          data-testid="snapshot-review-error"
          role="alert"
          aria-live="polite"
        >
          <span aria-hidden="true" className="mr-1">
            ⚠️
          </span>
          <span className="font-medium">加载失败</span>: {error}
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div
        className="space-y-3 p-4 border border-border rounded-md bg-bg-muted"
        data-testid="snapshot-review"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text">
            <span aria-hidden="true">📋</span> 快照审核 · {snapshotId}
          </h3>
          <button
            type="button"
            data-testid="snapshot-review-apply-all"
            disabled
            aria-label="应用所选字段"
            className="px-3 py-1.5 text-xs border border-border rounded text-text bg-bg hover:bg-bg-hover disabled:opacity-50"
          >
            应用所选字段
          </button>
        </div>
        <div className="p-4 text-xs text-muted" data-testid="snapshot-review-empty">
          没有待审核的差异项
        </div>
      </div>
    );
  }

  // 整组级别「应用所选字段」按钮：仅在有 pending + 用户有勾选时可用
  const anyPending = items.some((it) => it.status === 'pending');
  const hasAnySelection = items.some((it) => (selectedFields[it.id]?.size ?? 0) > 0);
  const applyAllDisabled = submitting || !anyPending || !hasAnySelection;

  async function handleApplyAll(): Promise<void> {
    setSubmitting(true);
    setStatusBanner(null);
    try {
      for (const item of items) {
        if (!mountedRef.current) return;
        if (item.status !== 'pending') continue;
        const fields = Array.from(selectedFields[item.id] ?? []);
        if (fields.length === 0) continue;
        try {
          await applyApi(snapshotId, item.id, fields, item.base_revision);
          if (!mountedRef.current) return;
        } catch (err) {
          if (!mountedRef.current) return;
          const msg = err instanceof Error ? err.message : String(err);
          if (/409|HTTP\s+409/.test(msg)) {
            setStatusBanner('快照已被修改, 已中止批量应用');
            await reload();
            return;
          }
          setStatusBanner(`批量应用失败 (${item.id}): ${msg}`);
          return;
        }
      }
      setStatusBanner('批量应用完成');
      await reload();
    } finally {
      if (mountedRef.current) setSubmitting(false);
    }
  }

  return (
    <div
      className="space-y-3 p-4 border border-border rounded-md bg-bg-muted"
      data-testid="snapshot-review"
      role="region"
      aria-label="快照审核"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text">
          <span aria-hidden="true">📋</span> 快照审核 · {snapshotId}
        </h3>
        <button
          type="button"
          data-testid="snapshot-review-apply-all"
          onClick={() => void handleApplyAll()}
          disabled={applyAllDisabled}
          aria-label="应用所选字段"
          className="px-3 py-1.5 text-xs border border-border rounded text-text bg-bg hover:bg-bg-hover disabled:opacity-50"
        >
          {submitting ? '提交中…' : '应用所选字段'}
        </button>
      </div>

      {statusBanner && (
        <div
          className="text-xs px-2 py-1 border border-border rounded text-text"
          data-testid="snapshot-review-banner"
          role="status"
          aria-live="polite"
        >
          {statusBanner}
        </div>
      )}

      <div className="space-y-2" data-testid="snapshot-review-items">
        {items.map((item) => {
          const sel = selectedFields[item.id] ?? new Set();
          return (
            <div
              key={item.id}
              className="border border-border rounded p-2 bg-bg"
              data-testid={`snapshot-item-${item.id}`}
            >
              <div className="flex items-center justify-between mb-1">
                <div className="font-mono text-xs text-text">
                  {item.after.model_key.provider}/{item.after.model_key.model_id}
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={item.status} classification={item.classification} />
                  <button
                    type="button"
                    data-testid={`snapshot-item-ignore-${item.id}`}
                    onClick={() => void handleIgnore(item)}
                    disabled={submitting || item.status !== 'pending'}
                    className="px-2 py-0.5 text-xs border border-border rounded text-text hover:bg-bg-hover disabled:opacity-50"
                  >
                    忽略
                  </button>
                </div>
              </div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-text-muted">
                    <th className="font-normal pr-2 text-left">字段</th>
                    <th className="font-normal pr-2 text-left">来源</th>
                    <th className="font-normal pr-2 text-left">旧值</th>
                    <th className="font-normal pr-2 text-left">新值</th>
                    <th className="font-normal pr-2 text-left">保护</th>
                    <th className="font-normal pr-2 text-left">勾选</th>
                  </tr>
                </thead>
                <tbody>
                  {REVIEWABLE_FIELDS.map((field) => {
                    const isProtected = item.clear_fields.includes(field);
                    const isChecked = sel.has(field);
                    return (
                      <tr
                        key={field}
                        className="border-t border-border"
                        data-testid={`snapshot-field-${item.id}-${field}`}
                      >
                        <td className="pr-2 py-0.5 font-medium">{FIELD_LABELS[field]}</td>
                        <td className="pr-2 py-0.5">
                          <FieldSourceBadge classification={item.classification} />
                        </td>
                        <td className="pr-2 py-0.5 text-text-muted">
                          {formatFieldValue(field, getBeforeValue(item, field))}
                        </td>
                        <td className="pr-2 py-0.5 text-text">
                          {formatFieldValue(field, getAfterValue(item, field))}
                        </td>
                        <td className="pr-2 py-0.5">
                          {isProtected ? (
                            <span className="text-text-muted" aria-label="保护字段">
                              <span aria-hidden="true">🔒</span> 保护
                            </span>
                          ) : (
                            <span className="text-text-muted" aria-label="可覆盖字段">
                              —
                            </span>
                          )}
                        </td>
                        <td className="pr-2 py-0.5">
                          <input
                            type="checkbox"
                            data-testid={`snapshot-checkbox-${item.id}-${field}`}
                            disabled={isProtected || item.status !== 'pending'}
                            checked={isChecked}
                            onChange={() => toggle(item.id, field)}
                            aria-label={`勾选字段 ${FIELD_LABELS[field]}`}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="flex justify-end mt-2">
                <button
                  type="button"
                  data-testid={`snapshot-item-apply-${item.id}`}
                  onClick={() => void handleApply(item)}
                  disabled={submitting || item.status !== 'pending' || sel.size === 0}
                  className="px-2 py-0.5 text-xs border border-border rounded text-text hover:bg-bg-hover disabled:opacity-50"
                >
                  应用本项
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface StatusBadgeProps {
  status: 'pending' | 'applied' | 'ignored';
  classification: 'new' | 'updated' | 'conflict' | 'unchanged';
}

function StatusBadge({ status, classification }: StatusBadgeProps) {
  // 图标 + 文字 (WCAG 1.4.1: 不只用颜色)
  const map = {
    pending: { icon: '⏳', text: '待审核' },
    applied: { icon: '✅', text: '已应用' },
    ignored: { icon: '🚫', text: '已忽略' },
  } as const;
  const cls = map[status];
  const classLabel = {
    new: '新增',
    updated: '更新',
    conflict: '冲突',
    unchanged: '无变化',
  }[classification];
  return (
    <span
      className="text-[11px] inline-flex items-center gap-1"
      data-testid={`status-${status}-${classification}`}
    >
      <span aria-hidden="true">{cls.icon}</span>
      <span>{cls.text}</span>
      <span className="text-text-muted">· {classLabel}</span>
    </span>
  );
}

function FieldSourceBadge({
  classification,
}: {
  classification: 'new' | 'updated' | 'conflict' | 'unchanged';
}) {
  const map = {
    new: { icon: '🆕', text: '新增' },
    updated: { icon: '✏️', text: '更新' },
    conflict: { icon: '⚠️', text: '冲突' },
    unchanged: { icon: '✓', text: '无变化' },
  } as const;
  const cls = map[classification];
  return (
    <span className="text-[11px] inline-flex items-center gap-1">
      <span aria-hidden="true">{cls.icon}</span>
      <span>{cls.text}</span>
    </span>
  );
}

function getBeforeValue(item: SnapshotDiffItem, field: ReviewableField): unknown {
  if (!item.before) return null;
  return getReviewableValue(item.before, field);
}

function getAfterValue(item: SnapshotDiffItem, field: ReviewableField): unknown {
  return getReviewableValue(item.after, field);
}

function getReviewableValue(
  model: SnapshotDiffItem['after'],
  field: ReviewableField,
): SnapshotDiffItem['after'][ReviewableField] {
  if (field === 'price') return model.price;
  if (field === 'native') return model.native;
  if (field === 'capabilities') return model.capabilities;
  if (field === 'architecture') return model.architecture;
  return model.quantization;
}
