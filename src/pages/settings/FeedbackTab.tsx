import { useEffect, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';

import { SettingRow } from './components';

interface FeedbackConfigState {
  managerUrl: string;
  hasSecret: boolean;
  installationUuid: string;
  configured: boolean;
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function FeedbackTab() {
  const { t } = useI18n();
  const [config, setConfig] = useState<FeedbackConfigState | null>(null);
  const [managerUrl, setManagerUrl] = useState('');
  const [sharedSecret, setSharedSecret] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async (): Promise<void> => {
      try {
        const loaded = await window.electronAPI?.feedback?.getConfig();
        if (cancelled || !loaded) return;
        setConfig(loaded);
        setManagerUrl(loaded.managerUrl);
      } catch (err) {
        if (!cancelled) setLoadError(getErrorMessage(err));
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async (): Promise<void> => {
    setSaveError(null);
    setSaved(false);
    try {
      // 共享密钥输入框留空 = 不改动；传空串 = 清空。
      const patch: { managerUrl?: string; sharedSecret?: string } = { managerUrl };
      if (sharedSecret) patch.sharedSecret = sharedSecret;
      const next = await window.electronAPI?.feedback?.setConfig(patch);
      if (next) setConfig(next);
      setSharedSecret('');
      setSaved(true);
    } catch (err) {
      setSaveError(getErrorMessage(err));
    }
  };

  const handleClear = async (): Promise<void> => {
    setSaveError(null);
    setSaved(false);
    try {
      const next = await window.electronAPI?.feedback?.setConfig({
        managerUrl: '',
        sharedSecret: '',
      });
      if (next) setConfig(next);
      setManagerUrl('');
      setSharedSecret('');
    } catch (err) {
      setSaveError(getErrorMessage(err));
    }
  };

  const handleSync = async (): Promise<void> => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const stats = await window.electronAPI?.feedback?.syncNow();
      if (stats) {
        setSyncResult(
          t('settings.feedback.synced')
            .replace('{submitted}', String(stats.submitted))
            .replace('{received}', String(stats.received))
            .replace('{errors}', String(stats.errors)),
        );
      }
    } catch (err) {
      setSyncResult(getErrorMessage(err));
    } finally {
      setSyncing(false);
    }
  };

  const handleCopyUuid = async (): Promise<void> => {
    if (!config?.installationUuid) return;
    try {
      await navigator.clipboard?.writeText(config.installationUuid);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard 不可用时静默 —— UUID 文本仍可手动选中复制
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-ui-lg font-semibold text-ink">{t('settings.feedback.title')}</h3>
        <p className="text-ui-sm text-muted mt-1">{t('settings.feedback.desc')}</p>
      </div>

      {loadError && (
        <p role="alert" className="text-ui-sm text-danger">
          {loadError}
        </p>
      )}

      <SettingRow
        label={t('settings.feedback.manager_url.label')}
        desc={t('settings.feedback.manager_url.desc')}
        anchor="feedback_manager_url"
      >
        <input
          data-testid="feedback-manager-url"
          type="url"
          value={managerUrl}
          onChange={(e) => setManagerUrl(e.target.value)}
          placeholder={t('settings.feedback.manager_url.placeholder')}
          className="w-full px-3 py-1.5 text-ui-sm rounded-md border border-border bg-bg text-text placeholder:text-muted"
        />
      </SettingRow>

      <SettingRow
        label={t('settings.feedback.shared_secret.label')}
        desc={t('settings.feedback.shared_secret.desc')}
        anchor="feedback_shared_secret"
      >
        <input
          data-testid="feedback-shared-secret"
          type="password"
          value={sharedSecret}
          onChange={(e) => setSharedSecret(e.target.value)}
          placeholder={t('settings.feedback.shared_secret.placeholder')}
          className="w-full px-3 py-1.5 text-ui-sm rounded-md border border-border bg-bg text-text placeholder:text-muted"
        />
      </SettingRow>

      <SettingRow
        label={t('settings.feedback.installation_uuid')}
        desc={t('settings.feedback.installation_uuid.desc')}
        anchor="feedback_installation_uuid"
      >
        <div className="flex items-center gap-2">
          <code
            data-testid="feedback-installation-uuid"
            className="flex-1 px-3 py-1.5 text-ui-sm rounded-md border border-border bg-bg-muted text-text font-mono truncate"
          >
            {config?.installationUuid ?? '—'}
          </code>
          <button
            type="button"
            data-testid="feedback-copy-uuid"
            onClick={handleCopyUuid}
            className="px-3 py-1.5 text-ui-sm rounded-md border border-border text-text hover:bg-bg-hover"
          >
            {copied ? t('settings.feedback.copied') : t('settings.feedback.copy_uuid')}
          </button>
        </div>
      </SettingRow>

      <SettingRow
        label={t('settings.feedback.sync_now')}
        desc={t('settings.feedback.desc')}
        anchor="feedback_sync_now"
      >
        <div className="flex items-center gap-3">
          <button
            type="button"
            data-testid="feedback-sync-now"
            disabled={syncing}
            onClick={handleSync}
            className="px-3 py-1.5 text-ui-sm rounded-md border border-border text-text hover:bg-bg-hover disabled:opacity-50"
          >
            {syncing ? t('settings.feedback.syncing') : t('settings.feedback.sync_now')}
          </button>
          <span className="text-ui-sm text-muted">
            {config?.configured
              ? t('settings.feedback.configured')
              : t('settings.feedback.unconfigured')}
          </span>
        </div>
      </SettingRow>

      <div className="flex items-center gap-3">
        <button
          type="button"
          data-testid="feedback-save"
          onClick={handleSave}
          className="px-3 py-1.5 text-ui-sm rounded-md bg-primary text-white hover:opacity-90"
        >
          {t('settings.feedback.save')}
        </button>
        <button
          type="button"
          data-testid="feedback-clear"
          onClick={handleClear}
          className="px-3 py-1.5 text-ui-sm rounded-md border border-border text-text hover:bg-bg-hover"
        >
          {t('settings.feedback.cleared')}
        </button>
        {saved && (
          <span role="status" className="text-ui-sm text-success">
            {t('settings.feedback.saved')}
          </span>
        )}
        {syncResult && (
          <span role="status" className="text-ui-sm text-muted">
            {syncResult}
          </span>
        )}
      </div>

      {saveError && (
        <p role="alert" className="text-ui-sm text-danger">
          {saveError}
        </p>
      )}
    </div>
  );
}
