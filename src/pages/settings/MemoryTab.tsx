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

import { invoke } from '../../shared/api/desktopInvoke';

import type { EndpointsTabProps } from './components';
import { SettingRow, Toggle } from './components';

export function MemoryTab({ settings, updateSettings }: EndpointsTabProps) {
  const [embedderStatus, setEmbedderStatus] = useState<{
    type: string;
    dimensions: number;
    table: string | null;
    model_dir: string;
    model_ready: boolean;
    semantic: boolean;
  } | null>(null);
  const [selecting, setSelecting] = useState(false);

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

  // R19: 数据安全 —— 备份清单/手动备份/记忆导出
  const [backups, setBackups] = useState<
    { name: string; size_bytes: number; created_at: number }[]
  >([]);
  const [backingUp, setBackingUp] = useState(false);
  const [exportingMemory, setExportingMemory] = useState(false);

  const loadBackups = useCallback(async () => {
    try {
      const res = await invoke<{ backups: { name: string; size_bytes: number; created_at: number }[] }>(
        'system_backups_list',
      );
      setBackups(res.backups ?? []);
    } catch {
      setBackups([]);
    }
  }, []);

  useEffect(() => {
    void loadBackups();
  }, [loadBackups]);

  const handleBackupNow = useCallback(async () => {
    setBackingUp(true);
    try {
      await invoke('system_backup_create');
      await loadBackups();
    } catch {
      // 静默——列表不刷新即反映失败
    } finally {
      setBackingUp(false);
    }
  }, [loadBackups]);

  const handleExportMemory = useCallback(async () => {
    setExportingMemory(true);
    try {
      const data = await invoke<unknown>('memory_export');
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: 'application/json;charset=utf-8',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `sage-memory-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch {
      // 静默
    } finally {
      setExportingMemory(false);
    }
  }, []);

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
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">数据安全</h3>
        <p className="text-xs text-text-secondary mb-2">
          应用每日自动备份数据库（保留最近 7 份），也可手动立即备份；记忆支持导出为 JSON 文件。
        </p>
        <div className="flex gap-2 mb-3">
          <button
            type="button"
            data-testid="backup-now"
            disabled={backingUp}
            onClick={() => void handleBackupNow()}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            {backingUp ? '备份中…' : '立即备份'}
          </button>
          <button
            type="button"
            data-testid="export-memory"
            disabled={exportingMemory}
            onClick={() => void handleExportMemory()}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            {exportingMemory ? '导出中…' : '导出记忆 (JSON)'}
          </button>
        </div>
        {backups.length > 0 && (
          <ul className="text-xs text-text-secondary space-y-1" data-testid="backup-list">
            {backups.slice(0, 5).map((b) => (
              <li key={b.name} className="font-mono">
                {b.name} · {(b.size_bytes / 1024 / 1024).toFixed(1)} MB ·{' '}
                {new Date(b.created_at).toLocaleString()}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
