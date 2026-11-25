/**
 * 设置页「MinerU 文档解析」卡片：声明式 ExternalServiceCard + MinerU 专属文案。
 * 数据源：GET /api/v1/mineru/status、preferences KV `mineru_service`。
 */

import { useMemo } from 'react';

import { ExternalServiceCard } from '../../features/settings/externalServices/ExternalServiceCard';
import type { ExternalServiceUiSpec } from '../../features/settings/externalServices/registry';
import { mineruApi } from '../../shared/api/mineruApi';
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

export function MineruServiceCard() {
  const { t } = useI18n();

  const spec = useMemo<ExternalServiceUiSpec>(
    () => ({
      key: 'mineru_service',
      title: t('settings.mineru.title'),
      description: t('settings.mineru.desc'),
      statusEndpoint: '/api/v1/mineru/status',
      testId: 'mineru-service-card',
      defaults: { ...DEFAULT_CONFIG },
      fetchStatus: () => mineruApi.status(),
      fields: [
        {
          jsonKey: 'baseUrl',
          label: t('settings.mineru.base_url'),
          type: 'text',
          placeholder: 'http://10.0.0.8:8000',
        },
        {
          jsonKey: 'apiKey',
          label: t('settings.mineru.api_key'),
          type: 'password',
          placeholder: t('settings.mineru.api_key_placeholder'),
        },
        { jsonKey: 'enabled', label: t('settings.mineru.enabled'), type: 'boolean' },
        {
          jsonKey: 'useInChatAttachment',
          label: t('settings.mineru.chat_attachment'),
          type: 'boolean',
        },
      ],
      renderStatus: (status, config) => (
        <div className="space-y-2">
          <div className="text-xs" data-testid="mineru-status">
            {status.reachable
              ? t('settings.mineru.reachable').replace('{mode}', status.serverAuthMode ?? 'unknown')
              : t('settings.mineru.unreachable').replace('{reason}', status.reason || 'unknown')}
          </div>
          {status.reachable && status.serverAuthMode === 'required' && !config.apiKey && (
            <div className="rounded bg-red-50 p-2 text-xs text-red-700" role="alert">
              {t('settings.mineru.auth_required')}
            </div>
          )}
        </div>
      ),
    }),
    [t],
  );

  return <ExternalServiceCard spec={spec} />;
}
