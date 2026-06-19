import { clsx } from 'clsx';
import { useState } from 'react';

import {
  DEFAULT_ENDPOINT,
  type DiscoveredModel,
  type EndpointConfig,
  type ModelSelection,
} from '../entities/setting/types';
import {
  type ConnectionTestResult,
  testEndpointConnection,
} from '../features/manage-endpoints/api';
import { useSettings } from '../features/manage-settings/useSettings';
import { EvolutionLog } from '../widgets/evolution/EvolutionLog';
import { EvolutionPanel } from '../widgets/evolution/EvolutionPanel';

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

/* ---- General Tab ---- */

function GeneralTab({ resetSettings }: { resetSettings: () => void }) {
  const { settings, updateSettings } = useSettings();

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">外观</h3>
        <SettingRow label="紧凑模式" desc="减少间距，在同一屏幕内显示更多内容">
          <Toggle
            value={settings.compactMode}
            onChange={(v) => updateSettings({ compactMode: v })}
          />
        </SettingRow>
        <SettingRow label="流式输出" desc="逐字显示 AI 回复，而非等待全部生成完成">
          <Toggle value={settings.streaming} onChange={(v) => updateSettings({ streaming: v })} />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">对话</h3>
        <SettingRow label="自动记忆提取" desc="对话中自动识别并保存关键信息到记忆库">
          <Toggle value={settings.autoMemory} onChange={(v) => updateSettings({ autoMemory: v })} />
        </SettingRow>
        <SettingRow label="确认后再删除记忆" desc="删除记忆前弹出确认对话框">
          <Toggle
            value={settings.confirmDelete}
            onChange={(v) => updateSettings({ confirmDelete: v })}
          />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">数据</h3>
        <button
          onClick={resetSettings}
          className="px-3 py-1.5 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors"
        >
          恢复默认设置
        </button>
      </section>
    </div>
  );
}

/* ---- Endpoints Tab ---- */

interface EndpointsTabProps {
  settings: ReturnType<typeof useSettings>['settings'];
  updateSettings: ReturnType<typeof useSettings>['updateSettings'];
}

function EndpointsTab({ settings, updateSettings }: EndpointsTabProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<EndpointConfig>>({});
  const [testResult, setTestResult] = useState<Record<string, ConnectionTestResult>>({});
  const [testingId, setTestingId] = useState<string | null>(null);

  const handleAdd = () => {
    const newEndpoint: EndpointConfig = {
      ...DEFAULT_ENDPOINT,
      id: crypto.randomUUID(),
      name: '新端点',
    };
    updateSettings({ endpoints: [...settings.endpoints, newEndpoint] });
    setEditingId(newEndpoint.id);
    setEditForm({ name: '新端点', baseUrl: '', apiKey: '' });
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
    if (!ep.baseUrl || !ep.apiKey) return;
    setTestingId(ep.id);
    setTestResult((prev) => ({
      ...prev,
      [ep.id]: { success: false, message: '测试中...', latency: 0 },
    }));
    const result = await testEndpointConnection(
      ep.baseUrl,
      ep.apiKey,
      settings.modelSelections.chatModel.modelId ?? undefined,
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
      updateSettings({ endpoints: updated });
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text">端点配置</h3>
        <button
          onClick={handleAdd}
          className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover transition-colors"
        >
          + 添加端点
        </button>
      </div>

      {settings.endpoints.length === 0 && (
        <div className="text-center text-muted py-8 text-sm">
          暂无端点配置，点击"添加端点"开始配置
        </div>
      )}

      {settings.endpoints.map((ep) => {
        const isEditing = editingId === ep.id;
        const form = isEditing ? editForm : {};
        const name = form.name ?? ep.name;
        const baseUrl = form.baseUrl ?? ep.baseUrl;
        const apiKey = form.apiKey ?? ep.apiKey;
        const result = testResult[ep.id];

        return (
          <div key={ep.id} className="p-4 border rounded-radius-sm bg-surface">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-text">{name}</span>
                {ep.discoveredModels.length > 0 && (
                  <span className="text-[11px] text-muted">
                    {ep.discoveredModels.length} 个模型
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                {!isEditing && (
                  <button
                    onClick={() => {
                      setEditingId(ep.id);
                      setEditForm({ name: ep.name, baseUrl: ep.baseUrl, apiKey: ep.apiKey });
                    }}
                    className="text-xs text-muted hover:text-text transition-colors"
                  >
                    编辑
                  </button>
                )}
                <button
                  onClick={() => handleDelete(ep.id)}
                  className="text-xs text-error hover:text-red-700 transition-colors"
                >
                  删除
                </button>
              </div>
            </div>

            {isEditing ? (
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-muted block mb-1">名称</label>
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
                    placeholder="sk-..."
                    className="w-full px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleSave(ep.id)}
                    className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover transition-colors"
                  >
                    保存
                  </button>
                  <button
                    onClick={() => {
                      setEditingId(null);
                      setEditForm({});
                    }}
                    className="px-3 py-1.5 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors"
                  >
                    取消
                  </button>
                  {baseUrl && apiKey && (
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
                      {testingId === ep.id ? '测试中...' : '测试连接'}
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
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono text-muted truncate">
                  {ep.baseUrl || '未配置'}
                </span>
                {ep.baseUrl && ep.apiKey && (
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
                    {testingId === ep.id ? '测试中...' : '测试连接'}
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
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ---- Models Tab ---- */

/** A model entry grouped by its source endpoint for the dropdown */
interface GroupedModel {
  endpointId: string;
  endpointName: string;
  model: DiscoveredModel;
}

function ModelsTab({ settings, updateSettings }: EndpointsTabProps) {
  const endpointsWithModels = settings.endpoints.filter((ep) => ep.discoveredModels.length > 0);

  if (endpointsWithModels.length === 0) {
    return (
      <div className="text-center text-muted py-12 text-sm">
        请先在"端点"标签页中添加端点并测试连接
      </div>
    );
  }

  // Build grouped model lists per capability
  const groupModels = (capability: DiscoveredModel['capabilities'][number]): GroupedModel[] =>
    endpointsWithModels.flatMap((ep) =>
      ep.discoveredModels
        .filter((m) => m.capabilities.includes(capability))
        .map((model) => ({ endpointId: ep.id, endpointName: ep.name, model })),
    );

  const chatModels = groupModels('chat');
  const visionModels = groupModels('vision');
  const embeddingModels = groupModels('embedding');

  const { chatModel, visionModel, embeddingModel } = settings.modelSelections;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text">模型选择</h3>
          <p className="text-xs text-muted mt-0.5">
            {endpointsWithModels.length} 个端点，共{' '}
            {endpointsWithModels.reduce((sum, ep) => sum + ep.discoveredModels.length, 0)} 个模型
          </p>
        </div>
      </div>

      <ModelSelector
        label="对话模型"
        desc="用于文本对话（必填）"
        required
        groupedModels={chatModels}
        value={chatModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, chatModel: v } })
        }
      />
      <ModelSelector
        label="视觉理解模型"
        desc="用于图片识别（选填）"
        groupedModels={visionModels}
        value={visionModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, visionModel: v } })
        }
      />
      <ModelSelector
        label="向量/嵌入模型"
        desc="用于向量化和语义搜索（选填）"
        groupedModels={embeddingModels}
        value={embeddingModel}
        onChange={(v) =>
          updateSettings({ modelSelections: { ...settings.modelSelections, embeddingModel: v } })
        }
      />

      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-text">模型参数</h3>
        <SettingRow label="最大上下文长度" desc="单次对话发送给模型的最大 token 数">
          <input
            type="number"
            min={256}
            max={128000}
            value={settings.maxContext}
            onChange={(e) => updateSettings({ maxContext: Number(e.target.value) })}
            className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
          />
        </SettingRow>
        <SettingRow label="Temperature" desc="控制输出的随机性，0 最确定，1 最随机">
          <input
            type="number"
            min={0}
            max={2}
            step={0.1}
            value={settings.temperature}
            onChange={(e) => updateSettings({ temperature: Number(e.target.value) })}
            className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
          />
        </SettingRow>
      </div>
    </div>
  );
}

interface ModelSelectorProps {
  label: string;
  desc: string;
  required?: boolean;
  groupedModels: GroupedModel[];
  value: ModelSelection;
  onChange: (v: ModelSelection) => void;
}

function ModelSelector({
  label,
  desc,
  required,
  groupedModels,
  value,
  onChange,
}: ModelSelectorProps) {
  // Group by endpointId for optgroup rendering
  const groups = new Map<string, { name: string; models: DiscoveredModel[] }>();
  for (const gm of groupedModels) {
    const existing = groups.get(gm.endpointId);
    if (existing) {
      existing.models.push(gm.model);
    } else {
      groups.set(gm.endpointId, { name: gm.endpointName, models: [gm.model] });
    }
  }

  const hasValue =
    value.modelId &&
    groupedModels.some((gm) => gm.endpointId === value.endpointId && gm.model.id === value.modelId);

  return (
    <SettingRow label={label} desc={desc}>
      <div className="flex items-center gap-2">
        <select
          value={hasValue ? `${value.endpointId}::${value.modelId}` : ''}
          onChange={(e) => {
            const raw = e.target.value;
            if (!raw) {
              onChange({ endpointId: null, modelId: null });
              return;
            }
            const [endpointId, modelId] = raw.split('::');
            onChange({ endpointId, modelId });
          }}
          className={clsx(
            'px-2 py-1 border rounded-radius-sm text-xs font-mono bg-surface text-text',
            required && !hasValue ? 'border-error' : 'border-border',
          )}
        >
          <option value="">{required ? '-- 请选择 --' : '-- 不使用 --'}</option>
          {Array.from(groups.entries()).map(([endpointId, { name, models }]) => (
            <optgroup key={endpointId} label={name}>
              {models.map((m) => (
                <option key={`${endpointId}::${m.id}`} value={`${endpointId}::${m.id}`}>
                  {m.id}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {required && !hasValue && <span className="text-[11px] text-error">必填</span>}
      </div>
    </SettingRow>
  );
}

/* ---- Memory Tab ---- */

function MemoryTab({ settings, updateSettings }: EndpointsTabProps) {
  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">记忆管理</h3>
        <SettingRow label="本地存储路径" desc="记忆数据在本地文件系统中的存储位置">
          <input
            type="text"
            value="%APPDATA%\\Sage\\memory.db"
            readOnly
            className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-bg-muted text-text-secondary"
          />
        </SettingRow>
        <SettingRow label="同步到内部服务器" desc="联网时将记忆增量同步到企业内部服务器">
          <Toggle value={settings.autoMemory} onChange={(v) => updateSettings({ autoMemory: v })} />
        </SettingRow>
      </section>
    </div>
  );
}

/* ---- Network Tab ---- */

function NetworkTab({ settings, updateSettings }: EndpointsTabProps) {
  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">网络配置</h3>
        <SettingRow label="代理模式" desc="企业内部网络通常需要配置代理">
          <select
            value={settings.proxyMode}
            onChange={(e) =>
              updateSettings({ proxyMode: e.target.value as 'system' | 'custom' | 'direct' })
            }
            className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
          >
            <option value="system">系统代理</option>
            <option value="custom">自定义代理</option>
            <option value="direct">直连</option>
          </select>
        </SettingRow>
        <SettingRow label="代理地址" desc="HTTP 代理服务器地址">
          <input
            type="text"
            value={settings.proxyUrl}
            onChange={(e) => updateSettings({ proxyUrl: e.target.value })}
            className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
          />
        </SettingRow>
        <SettingRow label="TLS 版本" desc="Windows 7 最高支持 TLS 1.2">
          <select
            value={settings.tlsVersion}
            onChange={(e) => updateSettings({ tlsVersion: e.target.value as '1.2' | '1.3' })}
            className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
          >
            <option value="1.2">TLS 1.2</option>
            <option value="1.3">TLS 1.3</option>
          </select>
        </SettingRow>
      </section>
    </div>
  );
}

/* ---- Sub-components ---- */

interface SettingRowProps {
  label: string;
  desc: string;
  children: React.ReactNode;
}

function SettingRow({ label, desc, children }: SettingRowProps) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-border">
      <div>
        <div className="text-sm text-text">{label}</div>
        <div className="text-xs text-muted mt-0.5">{desc}</div>
      </div>
      <div>{children}</div>
    </div>
  );
}

interface ToggleProps {
  value: boolean;
  onChange: (v: boolean) => void;
}

function Toggle({ value, onChange }: ToggleProps) {
  return (
    <button
      className={`w-9 h-5 rounded-full relative transition-colors ${
        value ? 'bg-primary' : 'bg-border'
      }`}
      onClick={() => onChange(!value)}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-text-inverse transition-transform ${
          value ? 'translate-x-4' : ''
        }`}
      />
    </button>
  );
}
