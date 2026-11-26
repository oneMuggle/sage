/**
 * 通用外部服务卡片：按声明式 spec 渲染表单与状态区。
 * 配置存 preferences KV（JSON blob，apiKey 由后端加密），状态来自服务 status 端点。
 */

import { useCallback, useEffect, useState } from 'react';

import { backendRequest } from '../../../shared/api/backendRequest';
import { settingsClient } from '../../../shared/api/settingsClient';
import { useI18n } from '../../../shared/lib/i18n';

import type {
  ExternalServiceConfig,
  ExternalServiceField,
  ExternalServiceStatus,
  ExternalServiceUiSpec,
} from './registry';

interface ExternalServiceCardProps {
  spec: ExternalServiceUiSpec;
}

function parseConfig(raw: string | null, defaults: ExternalServiceConfig): ExternalServiceConfig {
  if (!raw) return { ...defaults };
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return { ...defaults };
    return { ...defaults, ...(parsed as ExternalServiceConfig) };
  } catch {
    return { ...defaults };
  }
}

function fetchStatusFromEndpoint(spec: ExternalServiceUiSpec): Promise<ExternalServiceStatus> {
  return backendRequest<ExternalServiceStatus>({ method: 'GET', path: spec.statusEndpoint });
}

export function ExternalServiceCard({ spec }: ExternalServiceCardProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<ExternalServiceStatus | null>(null);
  const [config, setConfig] = useState<ExternalServiceConfig>(() => ({ ...spec.defaults }));
  const [saving, setSaving] = useState(false);

  const refreshStatus = useCallback(() => {
    const fetchStatus = spec.fetchStatus;
    const request = fetchStatus
      ? Promise.resolve().then(() => fetchStatus())
      : fetchStatusFromEndpoint(spec);
    return request.catch(() => null);
  }, [spec]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([refreshStatus(), settingsClient.getPreference(spec.key).catch(() => null)]).then(
      ([nextStatus, raw]) => {
        if (cancelled) return;
        setStatus(nextStatus);
        setConfig(parseConfig(raw, spec.defaults));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [refreshStatus, spec.key, spec.defaults]);

  const save = async () => {
    setSaving(true);
    try {
      await settingsClient.setPreference(spec.key, JSON.stringify(config));
      setStatus(await refreshStatus());
    } finally {
      setSaving(false);
    }
  };

  const setField = (jsonKey: string, value: string | number | boolean) => {
    setConfig((prev) => ({ ...prev, [jsonKey]: value }));
  };

  const renderInput = (field: ExternalServiceField) => {
    const value = config[field.jsonKey];
    if (field.type === 'boolean') {
      return (
        <label key={field.jsonKey} className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => setField(field.jsonKey, e.target.checked)}
          />
          {field.label}
        </label>
      );
    }
    if (field.type === 'number') {
      return (
        <label key={field.jsonKey} className="block text-xs">
          {field.label}
          <input
            type="number"
            className="mt-1 w-full rounded border border-border px-2 py-1"
            placeholder={field.placeholder}
            min={field.min}
            max={field.max}
            step={field.step}
            value={String(value ?? '')}
            onChange={(e) =>
              setField(field.jsonKey, e.target.value === '' ? 0 : Number(e.target.value))
            }
          />
        </label>
      );
    }
    return (
      <label key={field.jsonKey} className="block text-xs">
        {field.label}
        <input
          type={field.type === 'password' ? 'password' : 'text'}
          className="mt-1 w-full rounded border border-border px-2 py-1"
          placeholder={field.placeholder}
          value={String(value ?? '')}
          onChange={(e) => setField(field.jsonKey, e.target.value)}
        />
      </label>
    );
  };

  const inputFields = spec.fields.filter((field) => field.type !== 'boolean');
  const toggleFields = spec.fields.filter((field) => field.type === 'boolean');

  const statusNode = status
    ? (spec.renderStatus?.(status, config) ?? (
        <div className="text-xs">
          {status.reachable
            ? t('settings.external_service.reachable').replace(
                '{mode}',
                status.serverAuthMode ?? 'unknown',
              )
            : t('settings.external_service.unreachable').replace(
                '{reason}',
                status.reason || 'unknown',
              )}
        </div>
      ))
    : null;

  return (
    <div className="space-y-3 rounded border border-border p-3" data-testid={spec.testId}>
      <div className="text-sm font-semibold">{spec.title}</div>
      <p className="text-xs text-muted">{spec.description}</p>

      {statusNode}

      {inputFields.map(renderInput)}
      {toggleFields.length > 0 && (
        <div className="flex gap-3 text-xs">{toggleFields.map(renderInput)}</div>
      )}

      <button
        type="button"
        className="rounded bg-accent px-3 py-1 text-xs text-white disabled:opacity-50"
        disabled={saving}
        onClick={save}
      >
        {t('settings.external_service.save')}
      </button>
    </div>
  );
}
