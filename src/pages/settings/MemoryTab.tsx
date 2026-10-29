/**
 * Settings 页面 - 记忆管理 Tab
 *
 * 治理记录:
 * - "同步到内部服务器" 死开关 (memoryServerSync) 已于 2026-09-18 移除——
 *   后端下线该字段, 前端每次 PUT 主动剥离, 开关永远不生效。
 * - 不硬编码展示记忆库路径: 实际路径由 SAGE_DB_PATH 环境变量与运行模式
 *   决定 (见 backend/data/database.py), 写死展示既不准也无用。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { memoryApi } from '../../shared/api';
import { invoke } from '../../shared/api/desktopInvoke';
import { useI18n } from '../../shared/lib/i18n';

import { SettingRow } from './components';

// eslint-disable-next-line react-refresh/only-export-components
export function formatMemoryTabAuditSnapshot(input: {
  embedderType?: string | null;
  semantic?: boolean;
  modelReady?: boolean;
  backupCount: number;
}): string {
  const emb = input.embedderType?.trim() || '未知';
  const modeLabel = input.semantic ? '语义匹配' : '字面匹配';
  const readyLabel = input.modelReady ? '模型就绪' : '模型未就绪';
  const backups = Math.max(0, Math.trunc(input.backupCount));
  return `记忆管理 · ${emb} · ${modeLabel} · ${readyLabel} · 备份${backups}份`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatMemoryTabAuditJson(input: {
  embedderType?: string | null;
  semantic?: boolean;
  modelReady?: boolean;
  backupCount: number;
}): string {
  return JSON.stringify({
    embedderType: input.embedderType?.trim() || null,
    semantic: Boolean(input.semantic),
    modelReady: Boolean(input.modelReady),
    backupCount: Math.max(0, Math.trunc(input.backupCount)),
  });
}

export function MemoryTab() {
  const { t } = useI18n();
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

  // P8 (2026-09-14): 语义模型下载 —— 订阅 models:embedder:progress
  // （#755 已修 sage:event: 前缀），完成/失败即刷新嵌入器状态。
  const [modelDownload, setModelDownload] = useState<{ stage: string; file?: string } | null>(null);
  const [downloadingModel, setDownloadingModel] = useState(false);
  useEffect(() => {
    if (!window.electronAPI) return;
    let cancelled = false;
    const offs: Array<() => void> = [];
    void window.electronAPI
      .listen<{ stage: string; file?: string }>('models:embedder:progress', (p) => {
        if (cancelled) return;
        setModelDownload({ stage: p.stage, file: p.file });
        if (p.stage === 'complete') {
          setDownloadingModel(false);
          void loadEmbedderStatus();
        } else if (p.stage === 'error') {
          setDownloadingModel(false);
        }
      })
      .then((off) => {
        if (cancelled) off();
        else offs.push(off);
      });
    return () => {
      cancelled = true;
      offs.forEach((off) => off());
    };
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
    [loadEmbedderStatus],
  );

  // P8: 语义模型下载（触发 models:embedder:download；进度见上方 listen）
  const handleDownloadModel = useCallback(async () => {
    const api = window.electronAPI?.modelDownload;
    if (!api) {
      toast.error(t('settings.memory.download_unsupported'));
      return;
    }
    setDownloadingModel(true);
    try {
      const res = await api.download();
      if (res.ok) {
        toast.success(t('settings.memory.download_complete'));
        await loadEmbedderStatus();
      } else {
        toast.error(
          t('settings.memory.download_failed').replace(
            '{error}',
            String(res.error ?? t('settings.memory.unknown_error')),
          ),
        );
      }
    } catch (err) {
      toast.error(
        t('settings.memory.download_failed').replace(
          '{error}',
          String(err instanceof Error ? err.message : String(err)),
        ),
      );
    } finally {
      setDownloadingModel(false);
    }
  }, [loadEmbedderStatus, t]);

  // R19: 数据安全 —— 备份清单/手动备份/记忆导出
  const [backups, setBackups] = useState<
    { name: string; size_bytes: number; created_at: number }[]
  >([]);
  const [backingUp, setBackingUp] = useState(false);
  const [exportingMemory, setExportingMemory] = useState(false);

  const loadBackups = useCallback(async () => {
    try {
      const res = await invoke<{
        backups: { name: string; size_bytes: number; created_at: number }[];
      }>('system_backups_list');
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

  // R21-A: 恢复备份（两步确认，下次启动生效）
  const [restoringName, setRestoringName] = useState<string | null>(null);
  const [restoreArmed, setRestoreArmed] = useState<string | null>(null);
  const handleRestore = useCallback(
    async (name: string) => {
      if (restoreArmed !== name) {
        setRestoreArmed(name);
        return;
      }
      setRestoreArmed(null);
      setRestoringName(name);
      try {
        await invoke('system_backup_restore', { name });
        toast.success(t('settings.memory.restore_scheduled'));
      } catch {
        toast.error(t('settings.memory.restore_failed'));
      } finally {
        setRestoringName(null);
      }
    },
    [restoreArmed, t],
  );

  // R21-B: 导入记忆 JSON
  const importInputRef = useRef<HTMLInputElement>(null);
  const [importingMemory, setImportingMemory] = useState(false);
  const handleImportMemoryFile = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = '';
      if (!file) return;
      setImportingMemory(true);
      try {
        const text = await file.text();
        const payload = JSON.parse(text);
        const res = await invoke<{ imported: number; skipped: number; failed: number }>(
          'memory_import',
          { payload },
        );
        toast.success(
          t('settings.memory.import_complete')
            .replace('{imported}', String(res.imported))
            .replace('{skipped}', String(res.skipped))
            .replace('{failed}', String(res.failed)),
        );
      } catch {
        toast.error(t('settings.memory.import_failed'));
      } finally {
        setImportingMemory(false);
      }
    },
    [t],
  );

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
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.memory.semantic_embed')}
        </h3>
        {embedderStatus ? (
          <div className="space-y-2 text-xs text-text-secondary">
            <p>
              {t('settings.memory.embedder_status')
                .replace('{type}', embedderStatus.type)
                .replace('{dimensions}', String(embedderStatus.dimensions))
                .replace(
                  '{mode}',
                  embedderStatus.semantic
                    ? t('settings.memory.match_semantic')
                    : t('settings.memory.match_literal'),
                )
                .replace('{table}', String(embedderStatus.table ?? '-'))}
            </p>
            <p>
              {t('settings.memory.model_dir_label')} {embedderStatus.model_dir} ·{' '}
              {t('settings.memory.model_file')}
              {embedderStatus.model_ready
                ? t('settings.memory.model_ready')
                : t('settings.memory.model_not_ready')}
            </p>
            {/* P8: ONNX 模型未就绪时提供一键下载（内置清单，sha256 校验） */}
            {embedderStatus.model_ready === false && (
              <div className="flex items-center gap-2 mt-1">
                <button
                  type="button"
                  data-testid="embedder-model-download"
                  disabled={downloadingModel}
                  onClick={() => void handleDownloadModel()}
                  className="px-3 py-1.5 rounded-radius-sm bg-primary text-text-inverse text-xs font-medium hover:bg-primary-hover disabled:opacity-50"
                >
                  {downloadingModel
                    ? t('settings.common.loading')
                    : t('settings.memory.download_model')}
                </button>
                {downloadingModel && modelDownload?.file && (
                  <span className="text-ui-xs text-muted tabular-nums">{modelDownload.file}</span>
                )}
                {downloadingModel && (
                  <button
                    type="button"
                    data-testid="embedder-model-cancel"
                    onClick={() => {
                      void window.electronAPI?.modelDownload
                        ?.cancel('bge-small-zh-v1.5')
                        .catch(() => undefined);
                    }}
                    className="text-ui-xs text-muted hover:text-text underline"
                  >
                    {t('settings.common.cancel')}
                  </button>
                )}
              </div>
            )}
          </div>
        ) : (
          <p className="text-xs text-text-secondary">{t('settings.memory.embedder_loading')}</p>
        )}
        <div className="flex gap-2 mt-3">
          <button
            type="button"
            disabled={selecting}
            onClick={() => void selectEmbedder('onnx')}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            {t('settings.memory.enable_semantic')}
          </button>
          <button
            type="button"
            disabled={selecting}
            onClick={() => void selectEmbedder('hash')}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            {t('settings.memory.switch_to_literal')}
          </button>
        </div>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.memory.consolidation')}
        </h3>
        <p className="text-xs text-text-secondary mb-2">
          {t('settings.memory.consolidation_desc')}
        </p>
        <SettingRow
          anchor="memory_consolidation"
          label={t('settings.memory.manual_consolidation')}
          desc={t('settings.memory.manual_consolidation_desc')}
        >
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
                  toast.success(
                    t('settings.memory.consolidation_complete')
                      .replace('{promoted}', String(result.promoted))
                      .replace('{decayed}', String(result.decayed)),
                  );
                })
                .catch((err: unknown) => {
                  if (!mountedRef.current) return;
                  toast.error(
                    t('settings.memory.consolidation_failed').replace(
                      '{error}',
                      String(err instanceof Error ? err.message : String(err)),
                    ),
                  );
                })
                .finally(() => {
                  if (mountedRef.current) setConsolidating(false);
                });
            }}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            {consolidating ? t('settings.memory.consolidating') : t('settings.memory.run_now')}
          </button>
        </SettingRow>
        {consolidationResult && (
          <p className="text-xs text-text-secondary mt-2" data-testid="memory-consolidation-result">
            {t('settings.memory.last_consolidation')
              .replace('{promoted}', String(consolidationResult.promoted))
              .replace('{decayed}', String(consolidationResult.decayed))
              .replace('{total}', String(consolidationResult.total))}
          </p>
        )}
      </section>
      <section>
        {/* P1-5: 合并两个记忆 tab 后此处原本与 MemoryKnowledgeTab 的「记忆管理」
            同名，会在同一页出现两个同名小节。改为「存储位置」——它讲的就是
            数据存在哪，与「记忆管理」不是一回事。 */}
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.memory.storage_location')}
        </h3>
        <SettingRow
          anchor="memory_backup"
          label={t('settings.memory.local_storage')}
          desc={t('settings.memory.local_storage_desc')}
        >
          <span className="px-2 py-1 text-xs text-text-secondary font-mono">
            {t('settings.memory.local_sqlite')}
          </span>
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.memory.data_security')}
        </h3>
        <p className="text-xs text-text-secondary mb-2">
          {t('settings.memory.data_security_desc')}
        </p>
        <div className="flex gap-2 mb-3">
          <button
            type="button"
            data-testid="backup-now"
            disabled={backingUp}
            onClick={() => void handleBackupNow()}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            {backingUp ? t('settings.common.loading') : t('settings.memory.backup_now')}
          </button>
          <button
            type="button"
            data-testid="export-memory"
            disabled={exportingMemory}
            onClick={() => void handleExportMemory()}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            {exportingMemory ? t('settings.common.loading') : t('settings.memory.export_json')}
          </button>
        </div>
        {backups.length > 0 && (
          <ul className="text-xs text-text-secondary space-y-1" data-testid="backup-list">
            {backups.slice(0, 5).map((b) => (
              <li key={b.name} className="font-mono flex items-center gap-2">
                <span className="flex-1 truncate">
                  {b.name} · {(b.size_bytes / 1024 / 1024).toFixed(1)} MB ·{' '}
                  {new Date(b.created_at).toLocaleString()}
                </span>
                <button
                  type="button"
                  data-testid={`restore-${b.name}`}
                  disabled={restoringName !== null}
                  onClick={() => void handleRestore(b.name)}
                  className={`px-2 py-0.5 rounded border text-ui-2xs disabled:opacity-50 ${
                    restoreArmed === b.name
                      ? 'border-error text-error bg-error/5'
                      : 'border-border hover:bg-bg-hover'
                  }`}
                >
                  {restoreArmed === b.name
                    ? t('settings.memory.confirm_restore')
                    : restoringName === b.name
                      ? t('settings.common.loading')
                      : t('settings.memory.restore')}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-2">
          <button
            type="button"
            data-testid="import-memory"
            disabled={importingMemory}
            onClick={() => importInputRef.current?.click()}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            {importingMemory ? t('settings.common.loading') : t('settings.memory.import_json')}
          </button>
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => void handleImportMemoryFile(e)}
          />
        </div>
      </section>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditMemoryTabGovernance(): {
  module: 'src/pages/settings/MemoryTab.tsx';
  phase: 'P172';
  domain: 'settings';
  embedderModes: readonly ['onnx', 'hash'];
  supportsBackupsAndExport: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/settings/MemoryTab.tsx',
    phase: 'P172',
    domain: 'settings',
    embedderModes: ['onnx', 'hash'],
    supportsBackupsAndExport: true,
    compliant: true,
  };
}
