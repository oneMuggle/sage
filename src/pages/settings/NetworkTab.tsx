/**
 * Settings 页面 - 网络 Tab（内网 Web 访问）
 *
 * 配置走 preferences KV 的 network_policy key（JSON 字符串），与 permission_mode
 * 同一路径。不进 app_settings blob —— 后者有 LEGAL_TOP_KEYS 白名单校验，加顶层
 * 字段要同步改前端 AppSettings、后端白名单、契约测试三处。
 */

import { useEffect, useState } from 'react';

import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import { SettingRow } from './components';

/** 与后端 NetworkMode 枚举值一致（backend/domain/network_policy.py） */
export const NETWORK_MODES = ['online', 'intranet', 'offline'] as const;
export type NetworkMode = (typeof NETWORK_MODES)[number];

interface NetworkPolicyPayload {
  mode: NetworkMode;
  allowed_hosts: string[];
  insecure_tls_hosts: string[];
}

const DEFAULT_POLICY: NetworkPolicyPayload = {
  mode: 'online',
  allowed_hosts: [],
  insecure_tls_hosts: [],
};

function normalizeHost(value: string): string {
  return value.trim().toLowerCase().replace(/\.+$/, '');
}

/**
 * 与后端 host_matches 同语义：`*.` 通配命中 apex 自身及任意层级子域。
 * 后缀混淆（evilcnki.net vs *.cnki.net）不命中。
 */
function hostMatches(host: string, pattern: string): boolean {
  const h = normalizeHost(host);
  const p = normalizeHost(pattern);
  if (!p.startsWith('*.')) return h === p;
  const apex = p.slice(2);
  return h === apex || h.endsWith(`.${apex}`);
}

/**
 * 与后端 _validate_pattern 同语义。返回 null 表示合法，否则返回 i18n key。
 *
 * 先判是否含 `*` 再看前缀：normalizeHost 的尾点剥离会把 `*.` 变成 `*`，
 * 只用 startsWith('*.') 判断会让 `*` 和 `*.` 双双漏过。
 */
function validatePattern(raw: string): TranslationKey | null {
  const value = normalizeHost(raw);
  if (!value) return 'settings.network.error.empty';
  if (!value.includes('*')) return null;
  if (!value.startsWith('*.')) return 'settings.network.error.wildcard_format';
  const apex = value.slice(2);
  if (apex.includes('*')) return 'settings.network.error.wildcard_format';
  if (!apex.includes('.')) return 'settings.network.error.wildcard_too_broad';
  return null;
}

function parsePolicy(raw: string | null): NetworkPolicyPayload {
  if (!raw) return DEFAULT_POLICY;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return DEFAULT_POLICY;
    const candidate = parsed as Partial<NetworkPolicyPayload>;
    const mode = (NETWORK_MODES as readonly string[]).includes(candidate.mode ?? '')
      ? (candidate.mode as NetworkMode)
      : 'online';
    return {
      mode,
      allowed_hosts: Array.isArray(candidate.allowed_hosts)
        ? candidate.allowed_hosts.filter((h): h is string => typeof h === 'string')
        : [],
      insecure_tls_hosts: Array.isArray(candidate.insecure_tls_hosts)
        ? candidate.insecure_tls_hosts.filter((h): h is string => typeof h === 'string')
        : [],
    };
  } catch {
    // 坏 JSON 回退 online —— 与后端 load_network_policy 的 fail-safe 方向一致
    return DEFAULT_POLICY;
  }
}

// ---------------------------------------------------------------------------
// Round 4 F1/F2：代理设置（web_proxy）与搜索引擎（search_config）
// ---------------------------------------------------------------------------

/** 与后端 http_factory.load_proxy_config 的 JSON 结构一致 */
interface ProxyPayload {
  http: string;
  https: string;
}

const DEFAULT_PROXY: ProxyPayload = { http: '', https: '' };

const PROXY_SCHEMES = ['http://', 'https://', 'socks5://'] as const;

/** 与后端 browser_proxy_flag/browser_proxy 行为一致：空 = 不启用 */
function parseProxy(raw: string | null): ProxyPayload {
  if (!raw) return DEFAULT_PROXY;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return DEFAULT_PROXY;
    const candidate = parsed as Partial<ProxyPayload>;
    return {
      http: typeof candidate.http === 'string' ? candidate.http.trim() : '',
      https: typeof candidate.https === 'string' ? candidate.https.trim() : '',
    };
  } catch {
    return DEFAULT_PROXY;
  }
}

/** 校验代理 URL；空串 = 清除（合法）。返回 null 表示合法，否则 i18n key。 */
function validateProxyUrl(raw: string): TranslationKey | null {
  const value = raw.trim();
  if (!value) return null;
  if (!PROXY_SCHEMES.some((scheme) => value.startsWith(scheme))) {
    return 'settings.network.proxy.error.scheme';
  }
  return null;
}

/** 与后端 SearchConfig 的 JSON 结构一致（order 之外的 key 字段 Round 3 起落库自动加密） */
interface SearchConfigPayload {
  order: string[];
  tavily_key: string;
  zhipu_key: string;
}

const SEARCH_ENGINES = ['bing', 'ddg', 'tavily', 'zhipu'] as const;
const DEFAULT_SEARCH_ORDER = ['bing', 'ddg'];

const DEFAULT_SEARCH_CONFIG: SearchConfigPayload = {
  order: DEFAULT_SEARCH_ORDER,
  tavily_key: '',
  zhipu_key: '',
};

function parseSearchConfig(raw: string | null): SearchConfigPayload {
  if (!raw) return DEFAULT_SEARCH_CONFIG;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return DEFAULT_SEARCH_CONFIG;
    const candidate = parsed as Partial<SearchConfigPayload>;
    const order = Array.isArray(candidate.order)
      ? candidate.order.filter(
          (e): e is (typeof SEARCH_ENGINES)[number] =>
            (SEARCH_ENGINES as readonly string[]).includes(e),
        )
      : [];
    return {
      order: order.length > 0 ? order : [...DEFAULT_SEARCH_ORDER],
      tavily_key: typeof candidate.tavily_key === 'string' ? candidate.tavily_key : '',
      zhipu_key: typeof candidate.zhipu_key === 'string' ? candidate.zhipu_key : '',
    };
  } catch {
    return DEFAULT_SEARCH_CONFIG;
  }
}

interface KeyFieldEditorProps {
  testId: string;
  label: string;
  value: string;
  onSave: (value: string) => void;
}

function KeyFieldEditor({ testId, label, value, onSave }: KeyFieldEditorProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(value);
  useEffect(() => {
    setDraft(value);
  }, [value]);

  return (
    <div className="flex items-center gap-2 py-1">
      <label htmlFor={testId} className="w-32 shrink-0 text-xs text-text">
        {label}
      </label>
      <input
        id={testId}
        data-testid={testId}
        type="password"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => onSave(draft.trim())}
        placeholder={t('settings.network.search.key.placeholder')}
        className="flex-1 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
      />
    </div>
  );
}

interface HostListEditorProps {
  testIdPrefix: string;
  label: string;
  hint: string;
  hosts: string[];
  onAdd: (host: string) => TranslationKey | null;
  onRemove: (index: number) => void;
}

function HostListEditor({
  testIdPrefix,
  label,
  hint,
  hosts,
  onAdd,
  onRemove,
}: HostListEditorProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<TranslationKey | null>(null);

  const handleAdd = (): void => {
    const rejection = onAdd(draft);
    setError(rejection);
    if (!rejection) setDraft('');
  };

  return (
    <div className="space-y-2 py-3 border-b border-border">
      <div className="text-sm text-text">{label}</div>
      <div className="text-xs text-muted">{hint}</div>

      <div className="flex items-center gap-2">
        <input
          data-testid={`${testIdPrefix}-input`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleAdd();
          }}
          placeholder="*.example.internal"
          className="flex-1 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
        />
        <button
          type="button"
          data-testid={`${testIdPrefix}-add`}
          onClick={handleAdd}
          className="px-3 py-1 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover transition-colors"
        >
          {t('settings.network.host.add')}
        </button>
      </div>

      {error && (
        <div data-testid={`${testIdPrefix}-error`} className="text-xs text-error">
          {t(error)}
        </div>
      )}

      {hosts.length === 0 ? (
        <div className="text-xs text-muted">{t('settings.network.host.empty')}</div>
      ) : (
        <ul className="space-y-1">
          {hosts.map((host, index) => (
            <li
              key={host}
              className="flex items-center justify-between px-2 py-1 text-xs bg-surface rounded-radius-sm"
            >
              <span className="text-text font-mono">{host}</span>
              <button
                type="button"
                data-testid={`${testIdPrefix}-remove-${index}`}
                onClick={() => onRemove(index)}
                className="text-error hover:text-red-700 transition-colors"
              >
                {t('settings.network.host.remove')}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function NetworkTab() {
  const { t } = useI18n();
  const [policy, setPolicy] = useState<NetworkPolicyPayload>(DEFAULT_POLICY);
  const [proxy, setProxy] = useState<ProxyPayload>(DEFAULT_PROXY);
  const [proxyError, setProxyError] = useState<TranslationKey | null>(null);
  const [searchConfig, setSearchConfig] = useState<SearchConfigPayload>(DEFAULT_SEARCH_CONFIG);

  useEffect(() => {
    let cancelled = false;
    void settingsClient.getPreference('network_policy').then((raw) => {
      if (!cancelled) setPolicy(parsePolicy(raw));
    });
    void settingsClient.getPreference('web_proxy').then((raw) => {
      if (!cancelled) setProxy(parseProxy(raw));
    });
    void settingsClient.getPreference('search_config').then((raw) => {
      if (!cancelled) setSearchConfig(parseSearchConfig(raw));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const persist = (next: NetworkPolicyPayload): void => {
    setPolicy(next);
    void settingsClient.setPreference('network_policy', JSON.stringify(next), 'network');
  };

  const handleModeChange = (mode: NetworkMode): void => {
    persist({ ...policy, mode });
  };

  const addAllowedHost = (raw: string): TranslationKey | null => {
    const rejection = validatePattern(raw);
    if (rejection) return rejection;
    const host = normalizeHost(raw);
    if (policy.allowed_hosts.some((existing) => normalizeHost(existing) === host)) {
      return 'settings.network.error.duplicate';
    }
    persist({ ...policy, allowed_hosts: [...policy.allowed_hosts, host] });
    return null;
  };

  const removeAllowedHost = (index: number): void => {
    const allowed = policy.allowed_hosts.filter((_, i) => i !== index);
    // 后端 __post_init__ 要求 insecure_tls_hosts ⊆ allowed_hosts；留下孤儿条目
    // 会让整份配置被拒并 fail-safe 回 online，所以同步剔除失去覆盖的豁免项。
    const insecure = policy.insecure_tls_hosts.filter((host) =>
      allowed.some((pattern) => hostMatches(host, pattern)),
    );
    persist({ ...policy, allowed_hosts: allowed, insecure_tls_hosts: insecure });
  };

  const addInsecureTlsHost = (raw: string): TranslationKey | null => {
    const rejection = validatePattern(raw);
    if (rejection) return rejection;
    const host = normalizeHost(raw);
    if (!policy.allowed_hosts.some((pattern) => hostMatches(host, pattern))) {
      return 'settings.network.error.tls_not_covered';
    }
    if (policy.insecure_tls_hosts.some((existing) => normalizeHost(existing) === host)) {
      return 'settings.network.error.duplicate';
    }
    persist({ ...policy, insecure_tls_hosts: [...policy.insecure_tls_hosts, host] });
    return null;
  };

  const removeInsecureTlsHost = (index: number): void => {
    persist({
      ...policy,
      insecure_tls_hosts: policy.insecure_tls_hosts.filter((_, i) => i !== index),
    });
  };

  // ---- F1 代理：单字段 blur 保存；非法不落盘 ----
  const saveProxy = (field: 'http' | 'https', raw: string): void => {
    const value = raw.trim();
    const rejection = validateProxyUrl(value);
    setProxyError(rejection);
    if (rejection) return;
    const next = { ...proxy, [field]: value };
    setProxy(next);
    void settingsClient.setPreference('web_proxy', JSON.stringify(next), 'network');
  };

  // ---- F2 搜索引擎：首选引擎 + key 字段（后端落库自动加密） ----
  const saveSearchConfig = (next: SearchConfigPayload): void => {
    setSearchConfig(next);
    const payload = {
      order: next.order,
      ...(next.tavily_key ? { tavily_key: next.tavily_key } : {}),
      ...(next.zhipu_key ? { zhipu_key: next.zhipu_key } : {}),
    };
    void settingsClient.setPreference('search_config', JSON.stringify(payload), 'network');
  };

  const changeFirstEngine = (first: (typeof SEARCH_ENGINES)[number]): void => {
    // 首选提前，其余保持默认/现有相对次序（与后端引擎链 fallback 语义一致）
    const rest = searchConfig.order.filter((e) => e !== first);
    saveSearchConfig({ ...searchConfig, order: [first, ...rest] });
  };

  return (
    <div className="space-y-2">
      <SettingRow
        label={t('settings.network.mode')}
        desc={t(`settings.network.mode.${policy.mode}.desc` as TranslationKey)}
      >
        <select
          data-testid="network-mode-select"
          aria-label={t('settings.network.mode')}
          value={policy.mode}
          onChange={(e) => handleModeChange(e.target.value as NetworkMode)}
          className="px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
        >
          {NETWORK_MODES.map((mode) => (
            <option key={mode} value={mode}>
              {t(`settings.network.mode.${mode}` as TranslationKey)}
            </option>
          ))}
        </select>
      </SettingRow>

      {policy.mode === 'intranet' && policy.allowed_hosts.length === 0 && (
        <div
          data-testid="empty-whitelist-warning"
          className="px-3 py-2 text-xs text-warning bg-surface rounded-radius-sm"
        >
          {t('settings.network.empty_whitelist_warning')}
        </div>
      )}

      {policy.mode === 'intranet' && (
        <>
          <HostListEditor
            testIdPrefix="allowed-host"
            label={t('settings.network.allowed_hosts')}
            hint={t('settings.network.allowed_hosts.hint')}
            hosts={policy.allowed_hosts}
            onAdd={addAllowedHost}
            onRemove={removeAllowedHost}
          />
          <HostListEditor
            testIdPrefix="insecure-tls"
            label={t('settings.network.insecure_tls')}
            hint={t('settings.network.insecure_tls.hint')}
            hosts={policy.insecure_tls_hosts}
            onAdd={addInsecureTlsHost}
            onRemove={removeInsecureTlsHost}
          />
        </>
      )}

      {/* F1 抓取代理（Round 2 批次2 后端：web_proxy KV，逐调用现读即时生效） */}
      <SettingRow label={t('settings.network.proxy')} desc={t('settings.network.proxy.hint')}>
        <div className="flex flex-col gap-1 w-64" data-testid="proxy-fields">
          <input
            data-testid="proxy-http-input"
            aria-label={t('settings.network.proxy.http')}
            value={proxy.http}
            onChange={(e) => setProxy({ ...proxy, http: e.target.value })}
            onBlur={(e) => saveProxy('http', e.target.value)}
            placeholder={t('settings.network.proxy.placeholder')}
            className="px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
          />
          <input
            data-testid="proxy-https-input"
            aria-label={t('settings.network.proxy.https')}
            value={proxy.https}
            onChange={(e) => setProxy({ ...proxy, https: e.target.value })}
            onBlur={(e) => saveProxy('https', e.target.value)}
            placeholder={t('settings.network.proxy.placeholder')}
            className="px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
          />
          {proxyError && (
            <div data-testid="proxy-error" className="text-xs text-error">
              {t(proxyError)}
            </div>
          )}
        </div>
      </SettingRow>

      {/* F2 搜索引擎（Round 1 批次1 后端：search_config KV，key 落库自动加密） */}
      <SettingRow label={t('settings.network.search')} desc={t('settings.network.search.hint')}>
        <div className="flex flex-col gap-1 w-64" data-testid="search-fields">
          <select
            data-testid="search-first-engine"
            aria-label={t('settings.network.search.first')}
            value={searchConfig.order[0] ?? 'bing'}
            onChange={(e) => changeFirstEngine(e.target.value as (typeof SEARCH_ENGINES)[number])}
            className="px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
          >
            {SEARCH_ENGINES.map((engine) => (
              <option key={engine} value={engine}>
                {t(`settings.network.search.engine.${engine}` as TranslationKey)}
              </option>
            ))}
          </select>
          <KeyFieldEditor
            testId="search-tavily-key"
            label={t('settings.network.search.tavily_key')}
            value={searchConfig.tavily_key}
            onSave={(value) => saveSearchConfig({ ...searchConfig, tavily_key: value })}
          />
          <KeyFieldEditor
            testId="search-zhipu-key"
            label={t('settings.network.search.zhipu_key')}
            value={searchConfig.zhipu_key}
            onSave={(value) => saveSearchConfig({ ...searchConfig, zhipu_key: value })}
          />
        </div>
      </SettingRow>
    </div>
  );
}
