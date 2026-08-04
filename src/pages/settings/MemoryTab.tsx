/**
 * Settings 页面 - 记忆管理 Tab
 *
 * Task 2 (Gap B): the auto_memory toggle is now wired to the IPC bridge
 * (window.electronAPI.memory.getAutoMemory / setAutoMemory) which hits
 * GET/PUT /api/v1/preferences/auto_memory — backed by the SettingsRepository
 * whitelist (auto_memory key added in this task).
 *
 * The renderer-side `useSettings().autoMemory` field still flows through the
 * AppSettings pipeline (settingsClient.setSettings → localStorage +
 * /api/v1/settings) for backward compat; we leave that wired but read its
 * source of truth for the toggle directly from the IPC bridge so the
 * backend's `MemoryLifecycleManager` gate and the UI stay in lockstep.
 */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import type { EndpointsTabProps } from './components';
import { SettingRow, Toggle } from './components';

export function MemoryTab({ settings, updateSettings }: EndpointsTabProps) {
  const navigate = useNavigate();
  // Source of truth = backend preference via IPC bridge.
  // null = not yet loaded OR backend returned null (default True).
  const [autoMemoryLoaded, setAutoMemoryLoaded] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      // electronAPI is optional per the augmentation (web-only renderers
      // may not have it); bail to True if absent.
      const api = window.electronAPI;
      if (!api) {
        if (!cancelled) setAutoMemoryLoaded(true);
        return;
      }
      try {
        const raw = await api.memory.getAutoMemory();
        if (cancelled) return;
        // null/undefined → default True (backward compat with prior users).
        if (raw === null || raw === undefined) {
          setAutoMemoryLoaded(true);
          return;
        }
        setAutoMemoryLoaded(String(raw).toLowerCase() === 'true');
      } catch {
        if (!cancelled) setAutoMemoryLoaded(true);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleAutoMemoryChange = async (next: boolean) => {
    setAutoMemoryLoaded(next);
    // Keep the AppSettings-level autoMemory in sync for legacy consumers.
    try {
      await updateSettings({ autoMemory: next });
    } catch {
      // settingsClient already warns on failure; the IPC bridge is the
      // authoritative channel for the backend gate, so we don't surface.
    }
    try {
      const api = window.electronAPI;
      if (!api) return;
      await api.memory.setAutoMemory({ value: next });
    } catch {
      // Best-effort: revert local state if the backend write fails so the
      // user isn't left looking at a stale "checked" state.
      setAutoMemoryLoaded(!next);
    }
  };

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
        <SettingRow label="自动记忆沉淀" desc="每轮对话后自动提取并保存有价值的点">
          <Toggle
            value={autoMemoryLoaded ?? true}
            onChange={handleAutoMemoryChange}
          />
        </SettingRow>
        <SettingRow label="同步到内部服务器" desc="联网时将记忆增量同步到企业内部服务器">
          <Toggle value={settings.autoMemory} onChange={(v) => updateSettings({ autoMemory: v })} />
        </SettingRow>
        <SettingRow label="记忆检索注入" desc="对话时自动注入相关记忆到上下文">
          <Toggle
            value={autoMemoryLoaded ?? true}
            onChange={handleAutoMemoryChange}
          />
        </SettingRow>
      </section>
      <section>
        <button
          type="button"
          onClick={() => navigate('/memory')}
          className="text-sm text-primary hover:underline"
        >
          查看记忆管理 →
        </button>
      </section>
    </div>
  );
}