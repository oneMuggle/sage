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

import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { memoryApi } from '../../shared/api';
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
  // R17-B: 记忆固化手动触发
  const [consolidating, setConsolidating] = useState(false);
  const [consolidationResult, setConsolidationResult] = useState<{
    promoted: number;
    decayed: number;
    total: number;
  } | null>(null);
  // 卸载守卫:异步回调不触碰已卸载组件的 state(避免 "setState on unmounted" 警告)
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

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
        <h3 className="text-sm font-semibold text-text mb-3">记忆固化</h3>
        <p className="text-xs text-text-secondary mb-2">
          每周日 04:30 自动执行：把访问频繁的短期记忆晋升为语义记忆，并衰减长期未访问的记忆。也可手动立即执行。
        </p>
        <SettingRow label="手动固化" desc="立即运行一次记忆固化任务（通常无需手动触发）">
          <button
            type="button"
            data-testid="memory-consolidation-run"
            disabled={consolidating}
            onClick={() => {
              setConsolidating(true);
              setConsolidationResult(null);
              void memoryApi
                .runConsolidation()
                .then((result) => {
                  if (!mountedRef.current) return;
                  setConsolidationResult(result);
                  toast.success(`固化完成：晋升 ${result.promoted} 条，衰减 ${result.decayed} 条`);
                })
                .catch((err: unknown) => {
                  if (!mountedRef.current) return;
                  toast.error(`固化失败: ${err instanceof Error ? err.message : String(err)}`);
                })
                .finally(() => {
                  if (mountedRef.current) setConsolidating(false);
                });
            }}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            {consolidating ? '固化中...' : '立即固化'}
          </button>
        </SettingRow>
        {consolidationResult && (
          <p className="text-xs text-text-secondary mt-2" data-testid="memory-consolidation-result">
            上次手动固化：晋升 {consolidationResult.promoted} 条 · 衰减 {consolidationResult.decayed}{' '}
            条 · 处理 {consolidationResult.total} 条
          </p>
        )}
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
    </div>
  );
}
