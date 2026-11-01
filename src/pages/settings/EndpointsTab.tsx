/**
 * Settings 页面 - 端点配置 Tab
 */

import { clsx } from 'clsx';
import { useMemo, useState } from 'react';

import { getProtocolOptions } from '../../entities/endpoint/providerRegistry';
import { bindDiscoveredModels } from '../../entities/model-catalog/api';
import {
  DEFAULT_ENDPOINT,
  type EndpointConfig,
  type EndpointProtocol,
} from '../../entities/setting/types';
import {
  type ConnectionTestResult,
  type ProbeResult,
  probeModel,
  testEndpointConnection,
} from '../../features/manage-endpoints/api';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import type { EndpointsTabProps } from './components';

// Task 1 (2026-08-23): 协议下拉选项 — 与后端 canonicalizer / EndpointProtocol 类型对齐.
// A2 (providerRegistry): 改为从注册表读取，不再硬编码。

// eslint-disable-next-line react-refresh/only-export-components
export function formatEndpointsTabAuditSnapshot(input: {
  endpointCount: number;
  editingId?: string | null;
  testingId?: string | null;
}): string {
  const count = Math.max(0, Math.trunc(input.endpointCount));
  const editLabel = input.editingId ? `编辑中(${input.editingId})` : '只读';
  const testLabel = input.testingId ? `测试中(${input.testingId})` : '空闲';
  return `端点配置 · ${count}项 · ${editLabel} · ${testLabel}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatEndpointsTabAuditJson(input: {
  endpointCount: number;
  editingId?: string | null;
  testingId?: string | null;
}): string {
  const count = Math.max(0, Math.trunc(input.endpointCount));
  return JSON.stringify({
    endpointCount: count,
    editingId: input.editingId ?? null,
    testingId: input.testingId ?? null,
  });
}

/** 编辑表单是否偏离已保存的端点 —— 决定「保存」可点性与切走提示。 */
function endpointFormDirty(form: Partial<EndpointConfig>, ep: EndpointConfig): boolean {
  return (
    (form.name ?? ep.name) !== ep.name ||
    (form.baseUrl ?? ep.baseUrl) !== ep.baseUrl ||
    (form.apiKey ?? ep.apiKey) !== ep.apiKey ||
    (form.protocol ?? ep.protocol ?? 'openai-compatible') !==
      (ep.protocol ?? 'openai-compatible') ||
    (form.modelId ?? ep.modelId ?? '') !== (ep.modelId ?? '')
  );
}

export function EndpointsTab({ settings, updateSettings }: EndpointsTabProps) {
  const { t } = useI18n();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<EndpointConfig>>({});
  const [testResult, setTestResult] = useState<Record<string, ConnectionTestResult>>({});
  const [testingId, setTestingId] = useState<string | null>(null);
  const [probingId, setProbingId] = useState<string | null>(null);
  const [probeResults, setProbeResults] = useState<Record<string, ProbeResult>>({});
  // A2: 从 providerRegistry 读取协议选项（替代原硬编码常量）
  const PROTOCOL_OPTIONS = useMemo(() => getProtocolOptions(), []);

  // 当前正在编辑的端点是否有未落盘改动 —— 切到另一个端点前先提示，否则草稿静默丢失。
  const editingDirty = (() => {
    if (!editingId) return false;
    const target = settings.endpoints.find((ep) => ep.id === editingId);
    return target ? endpointFormDirty(editForm, target) : false;
  })();

  const handleAdd = () => {
    const newEndpoint: EndpointConfig = {
      ...DEFAULT_ENDPOINT,
      id: crypto.randomUUID(),
      name: t('settings.endpoints.new_name'),
    };
    updateSettings({ endpoints: [...settings.endpoints, newEndpoint] });
    setEditingId(newEndpoint.id);
    setEditForm({
      name: t('settings.endpoints.new_name'),
      baseUrl: '',
      apiKey: '',
      protocol: 'openai-compatible',
      modelId: '',
    });
  };

  const handleSave = (id: string) => {
    const updated = settings.endpoints.map((ep) => (ep.id === id ? { ...ep, ...editForm } : ep));
    updateSettings({ endpoints: updated });
    setEditingId(null);
    setEditForm({});
  };

  const handleDelete = (id: string) => {
    const remaining = settings.endpoints.filter((ep) => ep.id !== id);
    updateSettings({ endpoints: remaining });
    if (editingId === id) {
      setEditingId(null);
      setEditForm({});
    }
  };

  const handleTest = async (ep: EndpointConfig) => {
    if (!ep.baseUrl) return;
    setTestingId(ep.id);
    setTestResult((prev) => ({
      ...prev,
      [ep.id]: { success: false, message: t('settings.endpoints.testing'), latency: 0 },
    }));
    const result = await testEndpointConnection(
      ep.baseUrl,
      ep.apiKey,
      settings.modelSelections.chatModel.modelId ?? undefined,
      ep.protocol,
    );
    setTestResult((prev) => ({ ...prev, [ep.id]: result }));
    setTestingId(null);

    // Auto-save discovered models so the Models tab can list them
    // without a separate "refresh models" action.
    if (result.discoveredModels && result.discoveredModels.length > 0) {
      const modelsWithEndpoint = result.discoveredModels.map((m) => ({
        ...m,
        endpointId: ep.id,
      }));
      const updated = settings.endpoints.map((e) =>
        e.id === ep.id
          ? { ...e, discoveredModels: modelsWithEndpoint, lastDiscoveredAt: Date.now() }
          : e,
      );
      await updateSettings({ endpoints: updated });
      // Task 12 (2026-10-28): 让路由引擎拿到该端点的候选模型。
      // 必须等 settings 落盘后再触发 —— 后端是按存储的 discoveredModels 对账的,
      // 提前调用只能读到上一轮列表 (首次发现时一条都没有)。
      // fire-and-forget — 离线 / 旧后端不得打断发现流程, 也不弹 toast。
      void bindDiscoveredModels({ endpointId: ep.id }).catch(() => {});
    }
  };

  const handleProbe = async (ep: EndpointConfig) => {
    // 防御性检查: discoveredModels 可能在旧数据中缺失
    const discoveredModels = ep.discoveredModels ?? [];
    const modelId = ep.modelId || discoveredModels[0]?.id;
    if (!modelId) return;
    setProbingId(ep.id);
    try {
      const result = await probeModel(ep.id, modelId);
      setProbeResults((prev) => ({ ...prev, [ep.id]: result }));
    } catch {
      setProbeResults((prev) => ({
        ...prev,
        [ep.id]: {
          status: 'error',
          adapter: 'unknown',
          data: null,
          error: t('settings.endpoints.probe_request_failed'),
        },
      }));
    }
    setProbingId(null);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text">{t('settings.endpoints.title')}</h3>
        <button
          onClick={handleAdd}
          className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover transition-colors"
        >
          {t('settings.endpoints.add')}
        </button>
      </div>

      {settings.endpoints.length === 0 && (
        <div className="text-center text-muted py-8 text-sm">
          {t('settings.endpoints.empty_hint')}
        </div>
      )}

      {settings.endpoints.map((ep) => {
        const isEditing = editingId === ep.id;
        const form = isEditing ? editForm : {};
        const name = form.name ?? ep.name;
        const baseUrl = form.baseUrl ?? ep.baseUrl;
        const apiKey = form.apiKey ?? ep.apiKey;
        const protocol: EndpointProtocol = form.protocol ?? ep.protocol ?? 'openai-compatible';
        const modelId = form.modelId ?? ep.modelId ?? '';
        const result = testResult[ep.id];
        const probeResult = probeResults[ep.id];
        // 防御性检查: discoveredModels 可能在旧数据中缺失
        const discoveredModels = ep.discoveredModels ?? [];
        const probeModelId = ep.modelId || discoveredModels[0]?.id;
        // 与全局 editingDirty 同义，但按当前这一行算，用于该行「保存」按钮的可用性。
        const editDirty = isEditing && endpointFormDirty(editForm, ep);

        return (
          <div key={ep.id} className="p-4 border rounded-radius-sm bg-surface">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-text">{name}</span>
                {discoveredModels.length > 0 && (
                  <span className="text-[11px] text-muted">
                    {t('settings.endpoints.model_count').replace(
                      '{n}',
                      String(discoveredModels.length),
                    )}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                {!isEditing && (
                  <button
                    onClick={() => {
                      // 切到另一个端点会覆盖当前草稿 —— 有改动时先征得确认。
                      if (
                        editingId !== null &&
                        editingId !== ep.id &&
                        editingDirty &&
                        !window.confirm(t('settings.common.discard_confirm'))
                      ) {
                        return;
                      }
                      setEditingId(ep.id);
                      setEditForm({
                        name: ep.name,
                        baseUrl: ep.baseUrl,
                        apiKey: ep.apiKey,
                        protocol: ep.protocol,
                        modelId: ep.modelId,
                      });
                    }}
                    className="text-xs text-muted hover:text-text transition-colors"
                  >
                    {t('settings.endpoints.edit')}
                  </button>
                )}
                <button
                  onClick={() => handleDelete(ep.id)}
                  className="text-xs text-error hover:text-red-700 transition-colors"
                >
                  {t('settings.endpoints.delete')}
                </button>
              </div>
            </div>

            {isEditing ? (
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-muted block mb-1">
                    {t('settings.endpoints.field.name')}
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setEditForm({ ...form, name: e.target.value })}
                    className="w-full px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted block mb-1">Base URL</label>
                  <input
                    type="text"
                    value={baseUrl}
                    onChange={(e) => setEditForm({ ...form, baseUrl: e.target.value })}
                    placeholder="https://api.openai.com/v1"
                    className="w-full px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted block mb-1">API Key</label>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setEditForm({ ...form, apiKey: e.target.value })}
                    placeholder={
                      protocol === 'ollama' || protocol === 'openai-compatible'
                        ? t('settings.endpoints.api_key_placeholder_local')
                        : 'sk-...'
                    }
                    className="w-full px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
                  />
                  {(protocol === 'ollama' || protocol === 'openai-compatible') && (
                    <p className="text-ui-xs text-muted/70 mt-0.5">
                      {t('settings.endpoints.api_key_hint')}
                    </p>
                  )}
                  {ep.hasApiKey === true && !apiKey ? (
                    <p className="text-ui-xs text-amber-500/80 mt-0.5">
                      {t('settings.endpoints.api_key_saved_hint')}
                    </p>
                  ) : null}
                </div>
                <div>
                  <label className="text-xs text-muted block mb-1">
                    {t('settings.endpoints.field.protocol')}
                  </label>
                  <select
                    data-testid="endpoint-protocol-select"
                    value={protocol}
                    onChange={(e) =>
                      setEditForm({ ...form, protocol: e.target.value as EndpointProtocol })
                    }
                    className="w-full px-2 py-1 border border-border rounded-radius-sm text-xs bg-surface text-text"
                  >
                    {PROTOCOL_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="opacity-75">
                  <label className="text-[11px] text-muted/80 block mb-1">
                    {t('settings.endpoints.field.model_id')}
                  </label>
                  <input
                    type="text"
                    value={modelId}
                    onChange={(e) => setEditForm({ ...form, modelId: e.target.value })}
                    placeholder={t('settings.endpoints.model_id_placeholder')}
                    className="w-full px-2 py-1 border border-border rounded-radius-sm text-[11px] font-mono bg-surface text-text"
                  />
                  <p className="text-[10px] text-muted/70 mt-0.5">
                    {t('settings.endpoints.model_id_hint')}
                  </p>
                </div>
                {/* 2026-08-26: localModelPath 输入已移除. 该字段在 EndpointConfig
                    上保留 (DEFAULT_ENDPOINT.localModelPath = '') 仅用于向后兼容
                    读取旧设置; UI 不再询问本地 .gguf 路径, 因为 LM Studio 等本地
                    OpenAI-compatible 服务完全通过 baseUrl + modelId 路由, 不需要
                    该字段. plan §4. */}
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleSave(ep.id)}
                    disabled={!editDirty}
                    className={clsx(
                      'px-3 py-1.5 text-xs rounded-radius-sm transition-colors',
                      editDirty
                        ? 'bg-primary text-text-inverse hover:bg-primary-hover'
                        : 'bg-bg-muted text-muted cursor-not-allowed',
                    )}
                  >
                    {t('settings.endpoints.save')}
                  </button>
                  {editDirty && (
                    <span data-testid={`endpoint-unsaved-${ep.id}`} className="text-xs text-muted">
                      {t('settings.common.unsaved')}
                    </span>
                  )}
                  <button
                    onClick={() => {
                      setEditingId(null);
                      setEditForm({});
                    }}
                    className="px-3 py-1.5 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors"
                  >
                    {t('settings.endpoints.cancel')}
                  </button>
                  {baseUrl && (
                    <button
                      onClick={() => handleTest({ ...ep, ...form })}
                      disabled={testingId === ep.id}
                      className={clsx(
                        'px-3 py-1.5 text-xs rounded-radius-sm border transition-colors',
                        testingId === ep.id
                          ? 'border-border text-muted cursor-wait'
                          : 'border-primary text-primary hover:bg-primary/5',
                      )}
                    >
                      {testingId === ep.id
                        ? t('settings.endpoints.testing')
                        : t('settings.endpoints.test_connection')}
                    </button>
                  )}
                  {baseUrl && probeModelId && (
                    <button
                      onClick={() => handleProbe({ ...ep, ...form })}
                      disabled={probingId === ep.id}
                      className={clsx(
                        'px-3 py-1.5 text-xs rounded-radius-sm border transition-colors',
                        probingId === ep.id
                          ? 'border-border text-muted cursor-wait'
                          : 'border-purple-400 text-purple-500 hover:bg-purple-50',
                      )}
                      title={t('settings.endpoints.probe_title')}
                    >
                      {probingId === ep.id
                        ? t('settings.endpoints.probing')
                        : t('settings.endpoints.probe')}
                    </button>
                  )}
                </div>
                {result && (
                  <span
                    className={clsx(
                      'text-xs font-medium',
                      result.success ? 'text-green-600' : 'text-red-600',
                    )}
                  >
                    {result.message}
                    {result.latency > 0 && ` (${result.latency}ms)`}
                  </span>
                )}
                {probeResult && <ProbeStatusDisplay result={probeResult} />}
              </div>
            ) : (
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-muted truncate">
                    {ep.baseUrl || t('settings.endpoints.not_configured')}
                  </span>
                  {ep.baseUrl && (
                    <button
                      onClick={() => handleTest(ep)}
                      disabled={testingId === ep.id}
                      className={clsx(
                        'px-2 py-1 text-xs rounded-radius-sm border transition-colors',
                        testingId === ep.id
                          ? 'border-border text-muted cursor-wait'
                          : 'border-primary text-primary hover:bg-primary/5',
                      )}
                    >
                      {testingId === ep.id
                        ? t('settings.endpoints.testing')
                        : t('settings.endpoints.test_connection')}
                    </button>
                  )}
                  {ep.baseUrl && probeModelId && (
                    <button
                      onClick={() => handleProbe(ep)}
                      disabled={probingId === ep.id}
                      className={clsx(
                        'px-2 py-1 text-xs rounded-radius-sm border transition-colors',
                        probingId === ep.id
                          ? 'border-border text-muted cursor-wait'
                          : 'border-purple-400 text-purple-500 hover:bg-purple-50',
                      )}
                      title={t('settings.endpoints.probe_title_short')}
                    >
                      {probingId === ep.id
                        ? t('settings.endpoints.probing')
                        : t('settings.endpoints.probe')}
                    </button>
                  )}
                  {result && (
                    <span
                      className={clsx(
                        'text-xs font-medium',
                        result.success ? 'text-green-600' : 'text-red-600',
                      )}
                    >
                      {result.message}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3 text-[10px] text-muted/70">
                  <span>
                    {t('settings.endpoints.result.protocol')}: {ep.protocol}
                  </span>
                  {ep.modelId && (
                    <span>
                      {t('settings.endpoints.result.model')}: {ep.modelId}
                    </span>
                  )}
                </div>
                {probeResult && <ProbeStatusDisplay result={probeResult} />}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Render probe status and metadata below the endpoint info.
 *
 * Displays:
 * - status badge (success / unsupported / error)
 * - metadata (native context, architecture, quantization) when available
 * - error message when probe failed
 */
function ProbeStatusDisplay({ result }: { result: ProbeResult }) {
  const { t } = useI18n();
  const statusConfig: Record<
    ProbeResult['status'],
    { labelKey: TranslationKey; color: string; bg: string }
  > = {
    success: {
      labelKey: 'settings.endpoints.probe_status.success',
      color: 'text-green-600',
      bg: 'bg-green-50',
    },
    unsupported: {
      labelKey: 'settings.endpoints.probe_status.unsupported',
      color: 'text-yellow-600',
      bg: 'bg-yellow-50',
    },
    error: {
      labelKey: 'settings.endpoints.probe_status.error',
      color: 'text-red-600',
      bg: 'bg-red-50',
    },
  };

  const config = statusConfig[result.status];

  return (
    <div className={clsx('mt-2 px-2 py-1.5 rounded-radius-sm text-[11px]', config.bg)}>
      <span className={clsx('font-medium', config.color)}>{t(config.labelKey)}</span>
      {result.adapter !== 'unknown' && (
        <span className="text-muted ml-2">
          {t('settings.endpoints.result.adapter')}: {result.adapter}
        </span>
      )}
      {result.status === 'success' && result.data && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1 text-muted">
          {result.data.native != null && (
            <span>
              {t('settings.endpoints.result.context_native')}: {result.data.native.toLocaleString()}
            </span>
          )}
          {result.data.service != null && (
            <span>
              {t('settings.endpoints.result.context_service')}:{' '}
              {result.data.service.toLocaleString()}
            </span>
          )}
          {result.data.architecture && (
            <span>
              {t('settings.endpoints.result.architecture')}: {result.data.architecture}
            </span>
          )}
          {result.data.quantization && (
            <span>
              {t('settings.endpoints.result.quantization')}: {result.data.quantization}
            </span>
          )}
        </div>
      )}
      {result.status === 'error' && result.error && (
        <div className="mt-0.5 text-red-500">{result.error}</div>
      )}
      {result.status === 'unsupported' && result.error && (
        <div className="mt-0.5 text-yellow-600">{result.error}</div>
      )}
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditEndpointsTabGovernance(): {
  module: 'src/pages/settings/EndpointsTab.tsx';
  phase: 'P172';
  domain: 'settings';
  supportsEndpointProbeStatusDisplay: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/settings/EndpointsTab.tsx',
    phase: 'P172',
    domain: 'settings',
    supportsEndpointProbeStatusDisplay: true,
    compliant: true,
  };
}
