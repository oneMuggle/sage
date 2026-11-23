/**
 * 设置页「MinerU 文档解析」卡片：服务端状态 + 连接配置。
 * 数据源：GET /api/v1/mineru/status、preferences KV `mineru_service`。
 */

import { useEffect, useState } from 'react';

import { mineruApi, type MineruStatus } from '../../shared/api/mineruApi';
import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n } from '../../shared/lib/i18n';

export interface MineruServiceConfig {
  enabled: boolean;
  baseUrl: string;
  apiKey: string;
  defaultTier: 'flash' | 'basic' | 'standard' | 'advanced';
  timeoutSeconds: number;
  maxUploadMb: number;
  useInChatAttachment: boolean;
  minQualityThreshold: number;
}

const DEFAULT_CONFIG: MineruServiceConfig = {
  enabled: false,
  baseUrl: '',
  apiKey: '',
  defaultTier: 'standard',
  timeoutSeconds: 300,
  maxUploadMb: 25,
  useInChatAttachment: true,
  minQualityThreshold: 0.85,
};

function parseConfig(raw: string | null): MineruServiceConfig {
  if (!raw) return DEFAULT_CONFIG;
  try {
    const parsed = JSON.parse(raw) as Partial<MineruServiceConfig>;
    return { ...DEFAULT_CONFIG, ...parsed };
  } catch {
    return DEFAULT_CONFIG;
  }
}

export function MineruServiceCard() {
  const { t } = useI18n();
  const [status, setStatus] = useState<MineruStatus | null>(null);
  const [config, setConfig] = useState<MineruServiceConfig>(DEFAULT_CONFIG);
  const [saving, setSaving] = useState(false);

  const refreshStatus = () => mineruApi.status().catch(() => null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      refreshStatus(),
      settingsClient.getPreference('mineru_service').catch(() => null),
    ]).then(([nextStatus, raw]) => {
      if (cancelled) return;
      setStatus(nextStatus);
      setConfig(parseConfig(raw));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await settingsClient.setPreference('mineru_service', JSON.stringify(config));
      setStatus(await refreshStatus());
    } finally {
      setSaving(false);
    }
  };

  const authMismatch =
    status?.reachable && status.serverAuthMode === 'required' && !config.apiKey;

  return (
    <div
      className="space-y-3 rounded border border-border p-3"
      data-testid="mineru-service-card"
    >
      <div className="text-sm font-semibold">{t('settings.mineru.title')}</div>
      <p className="text-xs text-muted">{t('settings.mineru.desc')}</p>

      {status && (
        <div className="text-xs" data-testid="mineru-status">
          {status.reachable
            ? t('settings.mineru.reachable').replace('{mode}', status.serverAuthMode)
            : t('settings.mineru.unreachable').replace(
                '{reason}',
                status.reason || 'unknown',
              )}
        </div>
      )}
      {authMismatch && (
        <div className="rounded bg-red-50 p-2 text-xs text-red-700" role="alert">
          {t('settings.mineru.auth_required')}
        </div>
      )}

      <label className="block text-xs">
        {t('settings.mineru.base_url')}
        <input
          className="mt-1 w-full rounded border border-border px-2 py-1"
          placeholder="http://10.0.0.8:8000"
          value={config.baseUrl}
          onChange={(e) => setConfig({ ...config, baseUrl: e.target.value })}
        />
      </label>
      <label className="block text-xs">
        {t('settings.mineru.api_key')}
        <input
          type="password"
          className="mt-1 w-full rounded border border-border px-2 py-1"
          placeholder={t('settings.mineru.api_key_placeholder')}
          value={config.apiKey}
          onChange={(e) => setConfig({ ...config, apiKey: e.target.value })}
        />
      </label>

      <div className="flex gap-3 text-xs">
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={config.enabled}
            onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
          />
          {t('settings.mineru.enabled')}
        </label>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={config.useInChatAttachment}
            onChange={(e) =>
              setConfig({ ...config, useInChatAttachment: e.target.checked })
            }
          />
          {t('settings.mineru.chat_attachment')}
        </label>
      </div>

      <button
        type="button"
        className="rounded bg-accent px-3 py-1 text-xs text-white disabled:opacity-50"
        disabled={saving}
        onClick={save}
      >
        {t('settings.mineru.save')}
      </button>
    </div>
  );
}
