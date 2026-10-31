import { Cable, CheckCircle2, Copy, Laptop, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  createBrowserExtensionPairingCode,
  fetchBrowserExtensionStatus,
  revokeBrowserExtensionDevice,
  type BrowserExtensionDevice,
  type BrowserExtensionPairingCode,
  type BrowserExtensionStatus,
} from '../../shared/api/webAccessClient';
import { useI18n } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

interface BrowserExtensionSectionProps {
  /** 测试注入轮询间隔；线上 5s。 */
  pollIntervalMs?: number;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in vars ? String(vars[key]) : match,
  );
}

/**
 * 日常浏览器扩展：生成配对码、查看设备、撤销设备。
 *
 * 用户第一次看到这里时应该只需要理解「安装扩展 → 粘贴配对码」；
 * cookie/localStorage 等术语全部留给扩展弹窗里的「保存登录状态」。
 */
export function BrowserExtensionSection({ pollIntervalMs = 5000 }: BrowserExtensionSectionProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<BrowserExtensionStatus | null>(null);
  const [pairing, setPairing] = useState<BrowserExtensionPairingCode | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    const load = (): void => {
      fetchBrowserExtensionStatus()
        .then((next) => {
          if (alive) {
            setStatus(next);
            setError('');
          }
        })
        .catch((cause: unknown) => {
          if (alive) {
            setError(fill(t('settings.network.extension.error'), { error: errorText(cause) }));
          }
        });
    };
    load();
    const timer = window.setInterval(load, pollIntervalMs);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [pollIntervalMs, t]);

  const generate = async (): Promise<void> => {
    setBusy(true);
    try {
      setPairing(await createBrowserExtensionPairingCode());
    } catch (cause) {
      toast.error(
        fill(t('settings.network.extension.generate_failed'), { error: errorText(cause) }),
      );
    } finally {
      setBusy(false);
    }
  };

  const copyCode = async (code: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(code);
      toast.success(t('settings.network.extension.code.copied'));
    } catch (cause) {
      toast.error(errorText(cause));
    }
  };

  const revoke = async (device: BrowserExtensionDevice): Promise<void> => {
    const confirmed = await confirmDialog({
      title: t('settings.network.extension.revoke.confirm'),
      danger: true,
    });
    if (!confirmed) return;
    try {
      await revokeBrowserExtensionDevice(device.device_id);
      toast.success(t('settings.network.extension.revoked'));
      setStatus(await fetchBrowserExtensionStatus());
    } catch (cause) {
      toast.error(fill(t('settings.network.extension.revoke_failed'), { error: errorText(cause) }));
    }
  };

  const devices = status?.devices ?? [];
  const extensionDir = pairing?.extension_dir || status?.extension_dir || '';
  const baseUrl = pairing?.base_url || status?.base_url || '';
  const pairingExpired = !!pairing && Date.now() / 1000 >= pairing.expires_at;

  return (
    <section data-testid="browser-extension" data-settings-anchor="browser_extension">
      <h3 className="text-sm font-semibold text-text mb-3">{t('settings.network.extension')}</h3>
      <p className="text-xs text-muted mb-2">{t('settings.network.extension.hint')}</p>

      {error && (
        <div className="text-xs text-warning mb-2" data-testid="extension-error">
          {error}
        </div>
      )}

      <div
        className="flex flex-wrap items-center gap-2 text-xs mb-2"
        data-testid="extension-status"
      >
        <span
          className={
            status?.connected
              ? 'inline-flex items-center gap-1 px-2 py-0.5 rounded bg-success/10 text-success'
              : 'inline-flex items-center gap-1 px-2 py-0.5 rounded bg-bg-muted text-text-secondary'
          }
        >
          <Cable className="w-3 h-3" />
          {t(
            status?.connected
              ? 'settings.network.extension.connected'
              : 'settings.network.extension.disconnected',
          )}
        </span>
        {status?.shared && (
          <span
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-primary/10 text-primary"
            data-testid="extension-shared"
          >
            <Laptop className="w-3 h-3" />
            {fill(t('settings.network.extension.shared'), {
              title: status.shared.title || status.shared.host,
              host: status.shared.host,
            })}
          </span>
        )}
      </div>

      {devices.length === 0 ? (
        <div className="text-xs text-text-secondary mb-2" data-testid="extension-devices-empty">
          {t('settings.network.extension.devices.empty')}
        </div>
      ) : (
        <ul className="flex flex-col gap-1 mb-2" data-testid="extension-device-list">
          {devices.map((device) => (
            <li
              key={device.device_id}
              data-testid={`extension-device-${device.device_id}`}
              className="flex items-center gap-2 text-xs px-2 py-1.5 border border-border rounded-radius-sm"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-text-secondary shrink-0" />
              <span className="font-medium truncate">{device.label}</span>
              <span
                className={
                  device.connected
                    ? 'px-1.5 py-0.5 rounded bg-success/10 text-success'
                    : 'px-1.5 py-0.5 rounded bg-bg-muted text-text-secondary'
                }
              >
                {t(
                  device.connected
                    ? 'settings.network.extension.device.online'
                    : 'settings.network.extension.device.offline',
                )}
              </span>
              {device.sharing && (
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-primary/10 text-primary">
                  <CheckCircle2 className="w-3 h-3" />
                  {t('settings.network.extension.device.sharing')}
                </span>
              )}
              <button
                type="button"
                data-testid={`extension-revoke-${device.device_id}`}
                onClick={() => void revoke(device)}
                className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 text-xs border border-border rounded-radius-sm hover:bg-bg-muted"
              >
                <Trash2 className="w-3 h-3" />
                {t('settings.network.extension.revoke')}
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          data-testid="extension-generate"
          disabled={busy}
          onClick={() => void generate()}
          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-primary/40 bg-primary/10 text-primary rounded-radius-sm hover:bg-primary/20 disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${busy ? 'animate-spin' : ''}`} />
          {t(
            busy ? 'settings.network.extension.generating' : 'settings.network.extension.generate',
          )}
        </button>
      </div>

      {pairing && pairingExpired && (
        <div
          className="mt-2 p-2.5 border border-border bg-bg-muted rounded-radius-sm text-xs text-text-secondary"
          data-testid="extension-pairing-expired"
        >
          {t('settings.network.extension.code.expired')}
        </div>
      )}

      {pairing && !pairingExpired && (
        <div
          className="mt-2 p-2.5 border border-primary/30 bg-primary/5 rounded-radius-sm text-xs"
          data-testid="extension-pairing-code"
        >
          <div className="text-text-secondary mb-1">
            {t('settings.network.extension.code.title')}
          </div>
          <div className="flex items-center gap-2">
            <code className="text-lg font-semibold tracking-widest text-primary">
              {pairing.code}
            </code>
            <button
              type="button"
              data-testid="extension-copy-code"
              onClick={() => void copyCode(pairing.code)}
              className="inline-flex items-center gap-1 px-2 py-0.5 border border-border rounded-radius-sm hover:bg-bg-muted"
            >
              <Copy className="w-3 h-3" />
              {t('settings.network.extension.code.copy')}
            </button>
          </div>
          <div className="mt-1 text-text-secondary">
            {t('settings.network.extension.code.base_url')}: <code>{baseUrl}</code>
          </div>
        </div>
      )}

      <details className="mt-3" data-testid="extension-install">
        <summary className="text-xs text-text-secondary cursor-pointer select-none">
          {t('settings.network.extension.install')}
        </summary>
        <ol className="list-decimal list-inside mt-2 space-y-1 text-xs text-text-secondary">
          <li>{t('settings.network.extension.install.step1')}</li>
          <li>{t('settings.network.extension.install.step2')}</li>
          <li>{t('settings.network.extension.install.step3')}</li>
        </ol>
        <div className="mt-2 text-xs text-text-secondary break-all">
          {t('settings.network.extension.path')}:{' '}
          <code data-testid="extension-dir">
            {extensionDir || t('settings.network.extension.path.fallback')}
          </code>
        </div>
      </details>

      <p className="mt-2 text-xs text-muted">{t('settings.network.extension.privacy')}</p>
    </section>
  );
}
