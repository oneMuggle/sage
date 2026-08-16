/**
 * Settings 页面 - 记忆管理 Tab
 *
 * Task 2 (Gap B): the auto_memory toggle is wired to the IPC bridge
 * (window.electronAPI.memory.getAutoMemory / setAutoMemory) which hits
 * GET/PUT /api/v1/preferences/auto_memory — backed by the SettingsRepository
 * whitelist (auto_memory key added in this task).
 *
 * fix/security-perf-quickwins §1.3b f (2026-08-09, cherry-picked to win7):
 * - "同步到内部服务器" 开关从误绑的 `settings.autoMemory` 改为独立的
 *   `settings.memoryServerSync` 字段。`autoMemory` 实际语义是"对话中
 *   自动提取关键信息"（见 GeneralTab §"自动记忆提取"），与本 Tab
 *   的"同步到企业内部服务器"语义不同——同字段双语义是误导。
 * - 移除硬编码的 `%APPDATA%\Sage\memory.db` 展示：实际路径由
 *   SAGE_DB_PATH 环境变量决定（见 backend/data/database.py:158-173），
 *   写死展示既不准也无用。
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
  // Important-2: the "记忆检索注入" toggle drives its OWN preference
  // (memory_retrieval) — independent of auto_memory. Before this fix both
  // toggles shared autoMemoryLoaded + handleAutoMemoryChange, so flipping
  // one flipped the other.
  const [memoryRetrievalLoaded, setMemoryRetrievalLoaded] = useState<boolean | null>(null);

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

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const api = window.electronAPI;
      if (!api) {
        if (!cancelled) setMemoryRetrievalLoaded(true);
        return;
      }
      try {
        const raw = await api.memory.getMemoryRetrieval();
        if (cancelled) return;
        if (raw === null || raw === undefined) {
          setMemoryRetrievalLoaded(true);
          return;
        }
        setMemoryRetrievalLoaded(String(raw).toLowerCase() === 'true');
      } catch {
        if (!cancelled) setMemoryRetrievalLoaded(true);
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

  const handleMemoryRetrievalChange = async (next: boolean) => {
    setMemoryRetrievalLoaded(next);
    try {
      const api = window.electronAPI;
      if (!api) return;
      await api.memory.setMemoryRetrieval({ value: next });
    } catch {
      // Best-effort: revert local state if the backend write fails.
      setMemoryRetrievalLoaded(!next);
    }
  };

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">记忆管理</h3>
        <SettingRow
          label="本地存储"
          desc="记忆数据存储在本地 SQLite 数据库中，具体路径由 SAGE_DB_PATH 环境变量与运行模式决定"
        >
          <span className="px-2 py-1 text-xs text-text-secondary font-mono">
            本地 SQLite 数据库
          </span>
        </SettingRow>
        <SettingRow label="自动记忆沉淀" desc="每轮对话后自动提取并保存有价值的点">
          <Toggle value={autoMemoryLoaded ?? true} onChange={handleAutoMemoryChange} />
        </SettingRow>
        <SettingRow
          label="同步到内部服务器"
          desc="联网时将记忆增量同步到企业内部服务器（功能规划中，后端尚未接线）"
        >
          <Toggle
            value={settings.memoryServerSync}
            onChange={(v) => updateSettings({ memoryServerSync: v })}
          />
        </SettingRow>
        <SettingRow label="记忆检索注入" desc="对话时自动注入相关记忆到上下文">
          <Toggle
            value={memoryRetrievalLoaded ?? true}
            onChange={handleMemoryRetrievalChange}
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