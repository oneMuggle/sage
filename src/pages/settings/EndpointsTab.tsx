/**
 * Settings 页面 - 端点配置 Tab
 */

import { clsx } from 'clsx';
import { useState } from 'react';

import { DEFAULT_ENDPOINT, type EndpointConfig } from '../../entities/setting/types';
import {
  type ConnectionTestResult,
  testEndpointConnection,
} from '../../features/manage-endpoints/api';

import type { EndpointsTabProps } from './components';

export function EndpointsTab({ settings, updateSettings }: EndpointsTabProps) {
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
