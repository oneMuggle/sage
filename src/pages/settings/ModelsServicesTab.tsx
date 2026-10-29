/**
 * 模型与服务 — 合并自原 EndpointsTab + ModelsTab + ProvidersManager（2026-10-28 P1-b）。
 *
 * 页内子导航：端点 / 模型 / 更新源。更新源受 ENABLE_UPDATE_PROVIDERS_UI flag 控制。
 */
import { useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { useI18n } from '../../shared/lib/i18n';
import { ENABLE_UPDATE_PROVIDERS_UI } from '../../shared/updateFeatureFlag';
import { EndpointsTab } from './EndpointsTab';
import { ModelsTab } from './ModelsTab';
import { ProvidersManager } from './ProvidersManager';

type SubTab = 'endpoints' | 'models' | 'providers';

export function ModelsServicesTab(): JSX.Element {
  const { t } = useI18n();
  const { settings, updateSettings } = useSettings();
  const providersEnabled = ENABLE_UPDATE_PROVIDERS_UI();
  const [sub, setSub] = useState<SubTab>('models');

  return (
    <div className="space-y-4">
      <div className="flex gap-1 border-b border-border" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={sub === 'endpoints'}
          onClick={() => setSub('endpoints')}
          className={`px-3 py-1.5 text-ui-sm border-b-2 transition-colors ${
            sub === 'endpoints'
              ? 'border-primary text-primary font-medium'
              : 'border-transparent text-muted hover:text-text'
          }`}
        >
          {t('settings.tab.endpoints')}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={sub === 'models'}
          onClick={() => setSub('models')}
          className={`px-3 py-1.5 text-ui-sm border-b-2 transition-colors ${
            sub === 'models'
              ? 'border-primary text-primary font-medium'
              : 'border-transparent text-muted hover:text-text'
          }`}
        >
          {t('settings.tab.models')}
        </button>
        {providersEnabled && (
          <button
            type="button"
            role="tab"
            aria-selected={sub === 'providers'}
            onClick={() => setSub('providers')}
            className={`px-3 py-1.5 text-ui-sm border-b-2 transition-colors ${
              sub === 'providers'
                ? 'border-primary text-primary font-medium'
                : 'border-transparent text-muted hover:text-text'
            }`}
          >
            {t('settings.tab.providers')}
          </button>
        )}
      </div>
      <div role="tabpanel">
        {sub === 'endpoints' && <EndpointsTab settings={settings} updateSettings={updateSettings} />}
        {sub === 'models' && <ModelsTab settings={settings} updateSettings={updateSettings} />}
        {sub === 'providers' && providersEnabled && <ProvidersManager />}
      </div>
    </div>
  );
}
