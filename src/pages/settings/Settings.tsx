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
import { McpTab } from './McpTab';
import { MemoryTab } from './MemoryTab';
import { ModelsTab } from './ModelsTab';
import { NetworkTab } from './NetworkTab';

type SettingsTab = 'general' | 'endpoints' | 'models' | 'memory' | 'network' | 'mcp' | 'evolution';

export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const { settings, updateSettings, resetSettings } = useSettings();

  const tabs: { key: SettingsTab; label: string }[] = [
    { key: 'general', label: '通用' },
    { key: 'endpoints', label: '端点' },
    { key: 'models', label: '模型' },
    { key: 'memory', label: '记忆' },
    { key: 'network', label: '网络' },
    { key: 'mcp', label: 'MCP' },
    { key: 'evolution', label: '进化' },
  ];

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Left sub-nav (U15 from OpenWorker) */}
      <div className="w-52 border-r border-line bg-bg-muted flex-shrink-0">
        <div className="h-12 flex items-center px-4 border-b border-line">
          <h2 className="text-[16px] font-semibold text-ink">设置</h2>
        </div>
        <nav className="p-2 space-y-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={clsx(
                'w-full px-3 py-2 text-sm rounded-md transition-colors text-left',
                activeTab === tab.key
                  ? 'bg-primary text-text-inverse font-medium'
                  : 'text-muted hover:bg-bg-hover hover:text-ink',
              )}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Right content panel */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-3xl mx-auto">
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
            {activeTab === 'network' && <NetworkTab />}
            {activeTab === 'mcp' && <McpTab />}
            {activeTab === 'evolution' && (
              <div className="space-y-6">
                <EvolutionPanel />
                <EvolutionLog />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
