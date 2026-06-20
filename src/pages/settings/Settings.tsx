/**
 * Settings 页面 - 主容器
 */

import { clsx } from 'clsx';
import { useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { EvolutionLog } from '../../widgets/evolution/EvolutionLog';
import { EvolutionPanel } from '../../widgets/evolution/EvolutionPanel';
import { EndpointsTab } from './EndpointsTab';
import { GeneralTab } from './GeneralTab';
import { MemoryTab } from './MemoryTab';
import { ModelsTab } from './ModelsTab';
import { NetworkTab } from './NetworkTab';

type SettingsTab = 'general' | 'endpoints' | 'models' | 'memory' | 'network' | 'evolution';

export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const { settings, updateSettings, resetSettings } = useSettings();

  const tabs: { key: SettingsTab; label: string }[] = [
    { key: 'general', label: '通用' },
    { key: 'endpoints', label: '端点' },
    { key: 'models', label: '模型' },
    { key: 'memory', label: '记忆' },
    { key: 'network', label: '网络' },
    { key: 'evolution', label: '进化' },
  ];

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="h-12 flex items-center px-5 border-b border-border bg-surface flex-shrink-0">
        <h2 className="text-[18px] font-semibold text-text">设置</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        <div className="flex gap-1 border-b border-border mb-5">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={clsx(
                'px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
                activeTab === tab.key
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted hover:text-text',
              )}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === 'general' && <GeneralTab resetSettings={resetSettings} />}
        {activeTab === 'endpoints' && (
          <EndpointsTab settings={settings} updateSettings={updateSettings} />
        )}
        {activeTab === 'models' && (
          <ModelsTab settings={settings} updateSettings={updateSettings} />
        )}
        {activeTab === 'memory' && (
          <MemoryTab settings={settings} updateSettings={updateSettings} />
        )}
        {activeTab === 'network' && (
          <NetworkTab settings={settings} updateSettings={updateSettings} />
        )}
        {activeTab === 'evolution' && (
          <div className="space-y-6">
            <EvolutionPanel />
            <EvolutionLog />
          </div>
        )}
      </div>
    </div>
  );
}
