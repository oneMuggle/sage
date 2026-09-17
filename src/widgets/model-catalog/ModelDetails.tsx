/**
 * ModelDetails — 选中模型的详情面板 (Task 6, 2026-09-15)
 *
 * 显示 catalog 源视图 + effective 视图 (后端按优先级合并), 并提供:
 * - override 编辑 (native / price / capabilities / architecture / quantization)
 * - 探测按钮 (POST /probe)
 * - 409 stale revision 时弹"已被修改, 请重新确认"
 *
 * 约束:
 * - 价格永远从字符串原样回填, 不做算术
 * - null 显示"未知" 而非 "0"
 * - 状态图标 + 文字, 不只靠颜色
 */
import { useEffect, useMemo, useState } from 'react';

import {
  getEffective,
  probeModel,
  setOverride,
  deleteOverride,
} from '../../entities/model-catalog/api';
import type {
  CandidateModel,
  EffectiveModel,
  OverridePatch,
  ProbeResult,
} from '../../entities/model-catalog/types';
import { SOURCE_LABELS } from '../../entities/model-catalog/types';

interface ModelDetailsProps {
  item: CandidateModel | null;
  endpointId: string;
  onStatusChange: (status: string | null) => void;
  onReload?: () => Promise<void> | void;
}

function priceString(p: EffectiveModel['price'] | CandidateModel['price'] | undefined): string {
  if (!p) return '未知';
  const inV = p.input_per_million === null ? '未知' : `$${p.input_per_million}`;
  const outV = p.output_per_million === null ? '未知' : `$${p.output_per_million}`;
  return `入 ${inV} / 出 ${outV} (USD/M)`;
}

function sourceLabel(key: string | undefined): string {
  if (!key) return '未知';
  return SOURCE_LABELS[key] ?? key;
}

export function ModelDetails({ item, endpointId, onStatusChange, onReload }: ModelDetailsProps) {
  const [effective, setEffective] = useState<EffectiveModel | null>(null);
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [probeBusy, setProbeBusy] = useState(false);
  const [draft, setDraft] = useState<OverridePatch>({});
  const [saveBusy, setSaveBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  // Revision belongs to the selected model — keep it inside the component so
  // a switch from model A (rev=5) to model B cannot leak A's token into B's save.
  const [revision, setRevision] = useState(0);

  const modelKey = useMemo(
    () => (item ? `${item.model_key.provider}/${item.model_key.model_id}` : null),
    [item],
  );

  // 选中变更 → 拉 effective
  useEffect(() => {
    if (!item || !endpointId) {
      setEffective(null);
      setProbe(null);
      setRevision(0);
      setDraft({});
      setFeedback(null);
      setError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const eff = await getEffective(endpointId, item.model_key.model_id);
        if (!cancelled) {
          setEffective(eff);
          setRevision(eff?.revision ?? 0);
          setDraft({});
          setFeedback(null);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setEffective(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [item, endpointId]);

  // 探测成功后, 重新拉 effective — 服务探测层由后端持久化到 effective_data
  async function refreshEffective(): Promise<void> {
    if (!item || !endpointId) return;
    try {
      const eff = await getEffective(endpointId, item.model_key.model_id);
      setEffective(eff);
      setRevision(eff?.revision ?? 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  // 通知父级最新状态
  useEffect(() => {
    onStatusChange(error ?? feedback ?? null);
  }, [error, feedback, onStatusChange]);

  const draftKeys = Object.keys(draft);

  const hasUserOverride =
    effective?.provenance != null &&
    Object.values(effective.provenance).some((v) => v === 'user_override');

  if (!item) {
    return (
      <div
        className="p-3 text-xs text-text-muted border border-border rounded"
        data-testid="model-details-empty"
      >
        请从左侧目录选择一个模型查看详情
      </div>
    );
  }

  async function handleProbe(): Promise<void> {
    if (!item || !endpointId) return;
    setProbeBusy(true);
    setError(null);
    setFeedback(null);
    try {
      const result = await probeModel(endpointId, item.model_key.model_id);
      setProbe(result);
      setFeedback(
        result.status === 'success'
          ? '探测成功, 数据已更新'
          : result.status === 'unsupported'
            ? '当前端点不支持自动探测'
            : `探测失败: ${result.error ?? '未知'}`,
      );
      // 成功后立即刷新 effective — 后端把探测结果持久化进 effective_data 层
      if (result.status === 'success') {
        await refreshEffective();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setProbeBusy(false);
    }
  }

  async function handleSave(): Promise<void> {
    if (!item || !endpointId) return;
    setSaveBusy(true);
    setError(null);
    setFeedback(null);
    try {
      const result = await setOverride(endpointId, item.model_key.model_id, draft, revision);
      setRevision(result.revision);
      setDraft({});
      setFeedback('覆盖已保存');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (/409|HTTP\s+409/.test(msg)) {
        setError('字段已被其他进程修改, 请重新确认后再保存');
        // 409 后重新拉一次 effective — 拿回最新 revision + 可能被别人改的字段
        await refreshEffective();
      } else {
        setError(msg);
      }
    } finally {
      setSaveBusy(false);
    }
  }

  function setPriceField(field: 'input_per_million' | 'output_per_million', value: string): void {
    setDraft((prev) => {
      const base = prev.price ?? effective?.price ?? item!.price;
      const next = { ...base, [field]: value === '' ? null : value };
      return { ...prev, price: next };
    });
  }

  async function handleDeleteOverride(): Promise<void> {
    if (!item || !endpointId) return;
    setSaveBusy(true);
    setError(null);
    setFeedback(null);
    try {
      const result = await deleteOverride(endpointId, item.model_key.model_id, revision);
      setRevision(result.revision);
      setDraft({});
      setFeedback('已恢复继承');
      if (onReload) await onReload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (/409|HTTP\s+409/.test(msg)) {
        setError('覆盖已被其他进程修改, 请重新确认');
        await refreshEffective();
      } else {
        setError(msg);
      }
    } finally {
      setSaveBusy(false);
    }
  }

  return (
    <div
      className="border border-border rounded p-3 space-y-3"
      data-testid="model-details"
      aria-label={`模型详情 ${modelKey ?? ''}`}
    >
      <div>
        <h3 className="text-sm font-semibold">
          <span aria-hidden="true">🔍</span> {modelKey}
        </h3>
        <div className="text-[11px] text-text-muted">
          来源: {sourceLabel(effective?.provenance?.native)}
          {effective?.provenance?.price &&
          effective.provenance.price !== effective.provenance.native
            ? ` · 价格来源: ${sourceLabel(effective.provenance.price)}`
            : ''}
        </div>
      </div>

      {error && (
        <div
          className="text-xs px-2 py-1 border border-border rounded"
          role="alert"
          aria-live="polite"
          data-testid="model-details-error"
        >
          <span aria-hidden="true">⚠️</span> {error}
        </div>
      )}
      {feedback && !error && (
        <div
          className="text-xs px-2 py-1 border border-border rounded"
          role="status"
          aria-live="polite"
          data-testid="model-details-feedback"
        >
          <span aria-hidden="true">ℹ️</span> {feedback}
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 text-xs">
        <DetailRow label="上下文窗口">
          {effective?.limits.native === undefined
            ? '未知'
            : effective?.limits.native === null
              ? '未知'
              : `${effective.limits.native.toLocaleString()} tokens`}
        </DetailRow>
        <DetailRow label="服务窗口">
          {effective?.limits.service === null || effective?.limits.service === undefined
            ? '未知'
            : `${effective.limits.service.toLocaleString()} tokens`}
        </DetailRow>
        <DetailRow label="价格 (effective)">{priceString(effective?.price)}</DetailRow>
        <DetailRow label="价格 (catalog 源)">{priceString(item.price)}</DetailRow>
        <DetailRow label="架构">{item.architecture ?? '未知'}</DetailRow>
        <DetailRow label="量化">{item.quantization ?? '未知'}</DetailRow>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void handleProbe()}
          disabled={probeBusy || !endpointId}
          data-testid="model-details-probe"
          className="px-2 py-1 text-xs border border-border rounded hover:bg-bg-hover disabled:opacity-50"
        >
          {probeBusy ? '探测中…' : '探测'}
        </button>
      </div>

      {probe && (
        <div className="text-[11px] text-text-muted" data-testid="model-details-probe-result">
          探测状态: {probe.status} · 适配器: {probe.adapter}
        </div>
      )}

      <details className="text-xs">
        <summary className="cursor-pointer">手动覆盖 ({draftKeys.length} 项待保存)</summary>
        <div className="mt-2 space-y-2">
          <FieldRow
            label="native"
            testid="override-native"
            value={
              draft.native === undefined ? '' : draft.native === null ? '' : String(draft.native)
            }
            onChange={(v) =>
              setDraft((prev) => ({
                ...prev,
                native: v === '' ? null : Number(v),
              }))
            }
          />
          <FieldRow
            label="price.input"
            testid="override-price-input"
            value={
              draft.price?.input_per_million === undefined
                ? ''
                : (draft.price.input_per_million ?? '')
            }
            onChange={(v) => setPriceField('input_per_million', v)}
          />
          <FieldRow
            label="price.output"
            testid="override-price-output"
            value={
              draft.price?.output_per_million === undefined
                ? ''
                : (draft.price.output_per_million ?? '')
            }
            onChange={(v) => setPriceField('output_per_million', v)}
          />
          <FieldRow
            label="architecture"
            testid="override-architecture"
            value={draft.architecture === undefined ? '' : (draft.architecture ?? '')}
            onChange={(v) =>
              setDraft((prev) => ({
                ...prev,
                architecture: v === '' ? null : v,
              }))
            }
          />
          <FieldRow
            label="quantization"
            testid="override-quantization"
            value={draft.quantization === undefined ? '' : (draft.quantization ?? '')}
            onChange={(v) =>
              setDraft((prev) => ({
                ...prev,
                quantization: v === '' ? null : v,
              }))
            }
          />
          <div className="flex gap-2 justify-end">
            {hasUserOverride && (
              <button
                type="button"
                onClick={() => void handleDeleteOverride()}
                disabled={saveBusy || !endpointId}
                data-testid="override-restore"
                className="px-2 py-1 text-xs border border-border rounded hover:bg-bg-hover disabled:opacity-50"
              >
                {saveBusy ? '处理中…' : '恢复继承'}
              </button>
            )}
            <button
              type="button"
              onClick={() => setDraft({})}
              disabled={saveBusy || draftKeys.length === 0}
              data-testid="override-clear"
              className="px-2 py-1 text-xs border border-border rounded hover:bg-bg-hover disabled:opacity-50"
            >
              清空草稿
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saveBusy || draftKeys.length === 0 || !endpointId}
              data-testid="override-save"
              className="px-2 py-1 text-xs border border-border rounded hover:bg-bg-hover disabled:opacity-50"
            >
              {saveBusy ? '保存中…' : '保存覆盖'}
            </button>
          </div>
          <div className="text-[10px] text-text-muted">
            注: 空值代表「未知」(区别于 0); 价格保持字符串原样, 浏览器不参与计算。
          </div>
        </div>
      </details>
    </div>
  );
}

interface DetailRowProps {
  label: string;
  children: React.ReactNode;
}

function DetailRow({ label, children }: DetailRowProps) {
  return (
    <div className="flex flex-col">
      <span className="text-text-muted">{label}</span>
      <span className="font-medium">{children}</span>
    </div>
  );
}

interface FieldRowProps {
  label: string;
  testid: string;
  value: string;
  onChange: (v: string) => void;
}

function FieldRow({ label, testid, value, onChange }: FieldRowProps) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-text-muted">{label}</span>
      <input
        type="text"
        data-testid={testid}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="px-2 py-1 text-xs border border-border rounded bg-bg"
      />
    </label>
  );
}
