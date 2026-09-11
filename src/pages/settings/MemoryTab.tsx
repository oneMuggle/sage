/**
 * Settings 页面 - 记忆管理 Tab
 *
 * fix/security-perf-quickwins §1.3b f (2026-08-09):
 * - "同步到内部服务器" 开关从误绑的 `settings.autoMemory` 改为独立的
 *   `settings.memoryServerSync` 字段。`autoMemory` 实际语义是"对话中
 *   自动提取关键信息"（见 GeneralTab §"自动记忆提取"），与本 Tab
 *   的"同步到企业内部服务器"语义不同——同字段双语义是误导。
 * - 移除硬编码的 `%APPDATA%\Sage\memory.db` 展示（与 §1.4 "假功能/
 *   死设置清理" 同源治理）：实际路径由 SAGE_DB_PATH 环境变量决定
 *   （见 backend/data/database.py:158-173），Electron 模式下指向
 *   `%APPDATA%/Sage/sage.db`，dev 模式下指向 `<repo>/data/sage.db`，
 *   写死展示既不准也无用。
 */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { invoke } from '../../shared/api/desktopInvoke';

import type { EndpointsTabProps } from './components';
import { SettingRow, Toggle } from './components';

export function MemoryTab({ settings, updateSettings }: EndpointsTabProps) {
  const navigate = useNavigate();
  const [embedderStatus, setEmbedderStatus] = useState<{
    type: string;
    dimensions: number;
    table: string | null;
    model_dir: string;
    model_ready: boolean;
    semantic: boolean;
  } | null>(null);
  const [selecting, setSelecting] = useState(false);

  // ── win7 原有: auto_memory / memory_retrieval 偏好（IPC bridge）──────
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
      const api = window.electronAPI;
      if (!api) {
        if (!cancelled) setAutoMemoryLoaded(true);
        return;
      }
      try {
        const raw = await api.memory.getAutoMemory();
        if (cancelled) return;
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
    try {
      await updateSettings({ autoMemory: next });
    } catch {
      // settingsClient already warns on failure
    }
    try {
      const api = window.electronAPI;
      if (!api) return;
      await api.memory.setAutoMemory({ value: next });
    } catch {
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
      setMemoryRetrievalLoaded(!next);
    }
  };

  const loadEmbedderStatus = useCallback(async () => {
    try {
      const status = await invoke<{
        type: string;
        dimensions: number;
        table: string | null;
        model_dir: string;
        model_ready: boolean;
        semantic: boolean;
      }>('embedder_get_status');
      setEmbedderStatus(status);
    } catch {
      setEmbedderStatus(null);
    }
  }, []);

  useEffect(() => {
    void loadEmbedderStatus();
  }, [loadEmbedderStatus]);

  const selectEmbedder = useCallback(
    async (mode: 'onnx' | 'hash') => {
      setSelecting(true);
      try {
        await invoke('embedder_select', { mode });
        await loadEmbedderStatus();
      } catch {
        // 静默——状态刷新会反映真实情况
      } finally {
        setSelecting(false);
      }
    },
    [],
  );

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">语义嵌入 (检索增强)</h3>
        {embedderStatus ? (
          <div className="space-y-2 text-xs text-text-secondary">
            <p>
              当前嵌入器: {embedderStatus.type} · {embedderStatus.dimensions} 维 ·{' '}
              {embedderStatus.semantic ? '语义匹配' : '字面匹配'} · 表{' '}
              {embedderStatus.table ?? '-'}
            </p>
            <p>
              模型目录: {embedderStatus.model_dir} · 模型文件:
              {embedderStatus.model_ready ? '已就绪' : '未就绪'}
            </p>
          </div>
        ) : (
          <p className="text-xs text-text-secondary">嵌入器状态加载中…</p>
        )}
        <div className="flex gap-2 mt-3">
          <button
            type="button"
            disabled={selecting}
            onClick={() => void selectEmbedder('onnx')}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            启用语义嵌入
          </button>
          <button
            type="button"
            disabled={selecting}
            onClick={() => void selectEmbedder('hash')}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            切回字面匹配
          </button>
        </div>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">记忆管理</h3>        <SettingRow
          label="本地存储"
          desc="记忆数据存储在本地 SQLite 数据库中，具体路径由 SAGE_DB_PATH 环境变量与运行模式决定"
        >
          <span className="px-2 py-1 text-xs text-text-secondary font-mono">
            本地 SQLite 数据库
          </span>
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
        <SettingRow label="自动记忆沉淀" desc="每轮对话后自动提取并保存有价值的点">
          <Toggle value={autoMemoryLoaded ?? true} onChange={handleAutoMemoryChange} />
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
