// 对话阅读体验 C3（docs/mcp-chat-reading-nav-optimization.md §10.6）：云端模型端点不可达
// 时的全局提示条，挂在标题栏下方，所有页面可见。系统断网时单独提示。
import { CloudOff, RefreshCw, Settings, WifiOff, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { resolveEndpoint } from '../../entities/setting/types';
import { fetchModelsByProtocol } from '../../features/manage-endpoints/api';
import { useSettingsStore } from '../../features/manage-settings/settingsStore';
import {
  isSameEndpoint,
  useEndpointStatusStore,
  type EndpointIssue,
} from '../../shared/lib/endpointStatus';
import { fillTemplate } from '../../shared/lib/fillTemplate';
import { useI18n } from '../../shared/lib/i18n';

/** 设置页记住上次打开的 tab（Settings.tsx R45），跳转前写入即可落到端点页 */
const SETTINGS_TAB_STORAGE_KEY = 'sage:settings-tab';

export function formatEndpointStatusMarkdown(
  issue: EndpointIssue | null,
  online: boolean,
  text?: string,
): string {
  const lines = [
    '# 端点状态告警',
    `- 网络在线: ${online ? '是' : '否'}`,
  ];
  if (issue) {
    lines.push(`- 故障类型: ${issue.kind}`);
    lines.push(`- 端点主机: ${issue.host ?? issue.baseUrl ?? '—'}`);
    lines.push(`- 模型: ${issue.model ?? '—'}`);
    lines.push(`- 状态码: ${issue.status ?? '—'}`);
    lines.push(`- 详情: ${text || issue.message || '—'}`);
  }
  return lines.join('\n');
}

export function formatEndpointStatusJson(
  issue: EndpointIssue | null,
  online: boolean,
  text?: string,
): string {
  return JSON.stringify(
    {
      online,
      issue: issue
        ? {
            kind: issue.kind,
            baseUrl: issue.baseUrl ?? null,
            host: issue.host ?? null,
            model: issue.model ?? null,
            status: issue.status ?? null,
            message: issue.message ?? null,
          }
        : null,
      summary: text ?? null,
    },
    null,
    2,
  );
}

function isOnline(): boolean {
  return typeof navigator === 'undefined' || navigator.onLine !== false;
}

export function EndpointStatusBanner() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const issue = useEndpointStatusStore((s) => s.issue);
  const dismissed = useEndpointStatusStore((s) => s.dismissed);
  const settings = useSettingsStore((s) => s.settings);
  const [online, setOnline] = useState(isOnline);
  const [checking, setChecking] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  const endpoint = resolveEndpoint(settings.modelSelections.chatModel, settings.endpoints);

  const recheck = useCallback(
    async (silent: boolean) => {
      if (!endpoint?.baseUrl) return;
      setChecking(true);
      try {
        await fetchModelsByProtocol(
          endpoint.protocol ?? 'openai-compatible',
          endpoint.baseUrl,
          endpoint.apiKey,
        );
        useEndpointStatusStore.getState().clear();
        if (!silent) toast.success(t('endpoint.recovered'));
      } catch (err) {
        if (!silent) {
          const message = err instanceof Error ? err.message : String(err);
          toast.error(fillTemplate(t('endpoint.recheck_failed'), { message }));
        }
      } finally {
        setChecking(false);
      }
    },
    [endpoint, t],
  );
  const recheckRef = useRef(recheck);
  recheckRef.current = recheck;

  useEffect(() => {
    const onOnline = () => {
      setOnline(true);
      // 恢复联网时自动重新检测一次（静默：成功清除提示，失败保持原提示）
      if (useEndpointStatusStore.getState().issue) void recheckRef.current(true);
    };
    const onOffline = () => setOnline(false);
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    return () => {
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
    };
  }, []);

  if (!online) {
    return (
      <div
        role="status"
        data-testid="endpoint-banner-offline"
        className="flex items-center gap-2 px-4 py-1.5 text-xs bg-warning/10 text-text border-b border-warning/30"
      >
        <WifiOff className="w-3.5 h-3.5 text-warning shrink-0" aria-hidden="true" />
        <span className="flex-1">{t('endpoint.browser_offline')}</span>
      </div>
    );
  }

  // 用户已换成别的对话端点时，旧端点的提示不再相关
  const relevant =
    issue != null &&
    (!issue.baseUrl || !endpoint?.baseUrl || isSameEndpoint(issue.baseUrl, endpoint.baseUrl));
  if (!issue || dismissed || !relevant) return null;

  const host = issue.host ?? issue.baseUrl ?? '—';
  const key =
    issue.kind === 'timeout'
      ? 'endpoint.offline_timeout'
      : issue.kind === 'server'
        ? 'endpoint.offline_server'
        : 'endpoint.offline_network';
  const text =
    fillTemplate(t(key), { host, status: issue.status ?? '' }) +
    (issue.model ? fillTemplate(t('endpoint.offline_model'), { model: issue.model }) : '');

  const openSettings = () => {
    try {
      localStorage.setItem(SETTINGS_TAB_STORAGE_KEY, 'endpoints');
    } catch {
      /* ignore */
    }
    navigate('/settings');
  };

  /* v8 ignore start */
  const handleCopyMd = async () => {
    setCopiedMd(true);
    try {
      await navigator.clipboard?.writeText(formatEndpointStatusMarkdown(issue, online, text));
    } catch {
      // ignore clipboard errors in non-secure environments
    }
  };

  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(formatEndpointStatusJson(issue, online, text));
    } catch {
      // ignore clipboard errors in non-secure environments
    }
  };
  /* v8 ignore stop */

  return (
    <div
      role="alert"
      data-testid="endpoint-banner"
      className="flex items-center gap-2 px-4 py-1.5 text-xs bg-warning/10 text-text border-b border-warning/30"
    >
      <CloudOff className="w-3.5 h-3.5 text-warning shrink-0" aria-hidden="true" />
      <span className="flex-1 min-w-0 truncate" title={issue.message || text}>
        {text}
      </span>
      <button
        type="button"
        data-testid="endpoint-banner-copy-md"
        onClick={() => void handleCopyMd()}
        className="px-2 py-0.5 rounded hover:bg-bg-hover"
      >
        {copiedMd ? '已复制 MD' : '复制 MD'}
      </button>
      <button
        type="button"
        data-testid="endpoint-banner-copy-json"
        onClick={() => void handleCopyJson()}
        className="px-2 py-0.5 rounded hover:bg-bg-hover"
      >
        {copiedJson ? '已复制 JSON' : '复制 JSON'}
      </button>
      <button
        type="button"
        data-testid="endpoint-banner-recheck"
        onClick={() => void recheck(false)}
        disabled={checking || !endpoint?.baseUrl}
        className="flex items-center gap-1 px-2 py-0.5 rounded hover:bg-bg-hover disabled:opacity-50"
      >
        <RefreshCw className={`w-3 h-3 ${checking ? 'animate-spin' : ''}`} aria-hidden="true" />
        {checking ? t('endpoint.rechecking') : t('endpoint.recheck')}
      </button>
      <button
        type="button"
        data-testid="endpoint-banner-settings"
        onClick={openSettings}
        className="flex items-center gap-1 px-2 py-0.5 rounded hover:bg-bg-hover"
      >
        <Settings className="w-3 h-3" aria-hidden="true" />
        {t('endpoint.open_settings')}
      </button>
      <button
        type="button"
        data-testid="endpoint-banner-dismiss"
        onClick={() => useEndpointStatusStore.getState().dismiss()}
        className="p-1 rounded hover:bg-bg-hover"
        title={t('endpoint.dismiss')}
        aria-label={t('endpoint.dismiss')}
      >
        <X className="w-3 h-3" aria-hidden="true" />
      </button>
    </div>
  );
}
