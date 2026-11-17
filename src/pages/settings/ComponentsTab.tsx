import { Package, RefreshCw, Trash2, Upload } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import type {
  ComponentPackageSummary,
  InstalledComponentSummary,
} from '../../shared/types/electron-api';

interface ComponentProgress {
  op?: string;
  phase?: string;
  message?: string;
  done?: number;
  total?: number;
}

type BusyState = 'refresh' | 'scan' | 'import' | null;

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function ComponentsTab() {
  const { t } = useI18n();
  const api = window.electronAPI?.components;
  const [installed, setInstalled] = useState<InstalledComponentSummary[]>([]);
  const [discovered, setDiscovered] = useState<ComponentPackageSummary[]>([]);
  const [busy, setBusy] = useState<BusyState>(null);
  const [progress, setProgress] = useState<ComponentProgress | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const unsupported = !api;

  const refresh = useCallback(async () => {
    if (!api) return;
    setBusy('refresh');
    setError('');
    try {
      const result = await api.list();
      if (!result.ok) {
        setError(result.error ?? t('settings.components.error'));
        return;
      }
      setInstalled(result.installed);
      setDiscovered(result.discovered);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }, [api, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const bridge = window.electronAPI;
    if (!bridge?.listen) return;
    let unlisten: (() => void) | undefined;
    void bridge
      .listen<ComponentProgress>('components:progress', (event) => {
        setProgress(event);
      })
      .then((fn) => {
        unlisten = fn;
      });
    return () => {
      unlisten?.();
    };
  }, []);

  const handleImportResult = useCallback(
    async (result: { ok: boolean; error?: string; code?: string }) => {
      if (result.ok) {
        setMessage(t('settings.components.import_success'));
        await refresh();
        return;
      }
      if (result.code === 'cancelled') return;
      setError(result.error ?? t('settings.components.error'));
    },
    [refresh, t],
  );

  const onPickAndImport = useCallback(async () => {
    if (!api) return;
    setBusy('import');
    setError('');
    setMessage('');
    setProgress(null);
    try {
      await handleImportResult(await api.pickAndImport());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }, [api, handleImportResult]);

  const onImportPath = useCallback(
    async (path: string) => {
      if (!api) return;
      setBusy('import');
      setError('');
      setMessage('');
      setProgress(null);
      try {
        await handleImportResult(await api.importPath(path));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [api, handleImportResult],
  );

  const onScan = useCallback(async () => {
    if (!api) return;
    setBusy('scan');
    setError('');
    setMessage('');
    try {
      const result = await api.scan();
      if (!result.ok) {
        setError(result.error ?? t('settings.components.error'));
        return;
      }
      setDiscovered(result.discovered);
      setMessage(
        result.discovered.length
          ? t('settings.components.scan_success')
          : t('settings.components.scan_empty'),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }, [api, t]);

  const onRemove = useCallback(
    async (component: InstalledComponentSummary) => {
      if (!api) return;
      const prompt = t('settings.components.remove_confirm').replace('{name}', component.name);
      if (!window.confirm(prompt)) return;
      setBusy('import');
      setError('');
      setMessage('');
      try {
        const result = await api.remove(component.id);
        if (!result.ok) {
          setError(result.error ?? t('settings.components.error'));
          return;
        }
        setMessage(t('settings.components.remove_success'));
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [api, refresh, t],
  );

  const progressPercent = useMemo(() => {
    if (!progress?.total || !progress.done) return null;
    return Math.max(0, Math.min(100, Math.round((progress.done / progress.total) * 100)));
  }, [progress]);

  return (
    <div className="space-y-5" data-testid="components-tab">
      <div>
        <h3 className="text-ui-lg font-semibold text-ink">{t('settings.components.title')}</h3>
        <p className="mt-1 text-ui-sm text-muted">{t('settings.components.desc')}</p>
      </div>

      {unsupported ? (
        <div className="rounded-md border border-border bg-bg-muted px-3 py-2 text-ui-sm text-muted">
          {t('settings.components.unsupported')}
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="components-import"
            className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-ui-sm font-medium text-white disabled:opacity-50"
            disabled={busy !== null}
            onClick={() => void onPickAndImport()}
          >
            <Upload className="h-3.5 w-3.5" />
            {t('settings.components.import')}
          </button>
          <button
            type="button"
            data-testid="components-scan"
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-ui-sm text-ink disabled:opacity-50"
            disabled={busy !== null}
            onClick={() => void onScan()}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {t('settings.components.scan')}
          </button>
          <button
            type="button"
            data-testid="components-refresh"
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-ui-sm text-ink disabled:opacity-50"
            disabled={busy !== null}
            onClick={() => void refresh()}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {t('settings.components.refresh')}
          </button>
        </div>
      )}

      {busy === 'import' && (
        <div className="space-y-1" data-testid="components-progress">
          <div className="flex items-center justify-between text-ui-xs text-muted">
            <span>{progress?.message ?? t('settings.components.importing')}</span>
            {progressPercent !== null && <span>{progressPercent}%</span>}
          </div>
          <div className="h-1.5 overflow-hidden rounded bg-bg-muted">
            <div
              className="h-full rounded bg-accent transition-all"
              style={{ width: `${progressPercent ?? 10}%` }}
            />
          </div>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-ui-sm text-danger"
        >
          {error}
        </div>
      )}
      {message && (
        <div
          role="status"
          className="rounded-md border border-success/40 bg-success/10 px-3 py-2 text-ui-sm text-success"
        >
          {message}
        </div>
      )}

      <section className="space-y-2" data-testid="components-installed">
        <h4 className="text-ui-sm font-semibold text-ink">
          {t('settings.components.installed_title')}
        </h4>
        {installed.length === 0 ? (
          <p className="text-ui-sm text-muted">{t('settings.components.installed_empty')}</p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {installed.map((component) => (
              <li key={component.id} className="flex items-center gap-3 px-3 py-2">
                <Package className="h-4 w-4 flex-shrink-0 text-muted" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-ui-sm font-medium text-ink">
                      {component.name}
                    </span>
                    <span className="rounded bg-bg-muted px-1.5 py-0.5 text-ui-2xs text-muted">
                      {component.version}
                    </span>
                    {component.signatureVerified && (
                      <span className="text-ui-2xs text-success">
                        {t('settings.components.signature_ok')}
                      </span>
                    )}
                  </div>
                  <div className="truncate text-ui-xs text-muted">
                    {component.id} · {component.target} · {formatBytes(component.totalBytes)}
                  </div>
                </div>
                <button
                  type="button"
                  data-testid={`components-remove-${component.id}`}
                  aria-label={t('settings.components.remove')}
                  className="rounded p-1 text-muted hover:bg-bg-hover hover:text-danger disabled:opacity-50"
                  disabled={busy !== null}
                  onClick={() => void onRemove(component)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2" data-testid="components-discovered">
        <h4 className="text-ui-sm font-semibold text-ink">
          {t('settings.components.discovered_title')}
        </h4>
        {discovered.length === 0 ? (
          <p className="text-ui-sm text-muted">{t('settings.components.discovered_empty')}</p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {discovered.map((item, index) => (
              <li key={item.path} className="flex items-center gap-3 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-ui-sm text-ink">
                    {item.error ? item.path : `${item.name} ${item.version}`}
                  </div>
                  <div className="truncate text-ui-xs text-muted">
                    {item.error ? item.error : item.path}
                  </div>
                </div>
                {!item.error && (
                  <button
                    type="button"
                    data-testid={`components-import-${index}`}
                    className="rounded border border-border px-2 py-1 text-ui-xs text-ink disabled:opacity-50"
                    disabled={busy !== null}
                    onClick={() => void onImportPath(item.path)}
                  >
                    {t('settings.components.import')}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="text-ui-xs text-muted">{t('settings.components.security_note')}</p>
    </div>
  );
}
