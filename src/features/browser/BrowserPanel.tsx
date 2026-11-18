import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Camera,
  Globe,
  MousePointerClick,
  RotateCw,
  ScanEye,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import {
  fetchBrowserAudit,
  fetchBrowserControl,
  fetchBrowserControlSessions,
  fetchPendingConfirmations,
  resolveConfirmation,
  setBrowserControl,
  type BrowserAuditEntry,
  type BrowserControlState,
  type BrowserPendingConfirmation,
  type ConfirmationDecision,
} from '../../shared/api/browserControlClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { buildLocalImageSrc } from '../../shared/lib/localImageSrc';
import { useStore, type ToolCall } from '../../shared/lib/store';
import {
  isBrowserPanelAutoOpenEnabled,
  setBrowserPanelAutoOpenEnabled,
} from '../right-panel/rightPanelStore';

import { rememberBrowserSession, useBrowserSessionStore } from './browserSessionStore';
import {
  collectPersistedBrowserCalls,
  latestBrowserSessionId,
  mergeBrowserToolCalls,
} from './browserSteps';

type PanelApi = NonNullable<Window['electronAPI']>['browserPanel'];

function panelApi(): PanelApi | undefined {
  return typeof window !== 'undefined' ? window.electronAPI?.browserPanel : undefined;
}

/** 后端 ``_browser_meta`` 的字段子集（其余字段前端暂不消费）。 */
interface BrowserStepMeta {
  session_id?: string;
  action?: string;
  url?: string;
  title?: string;
  target_ref?: string;
  target_name?: string;
  login_wall?: boolean;
  screenshot_path?: string | null;
}

interface StepEnvelope {
  meta: BrowserStepMeta | null;
  success: boolean | null;
  error: string;
}

const EMPTY_ENVELOPE: StepEnvelope = { meta: null, success: null, error: '' };

/** 后端控制门禁的错误前缀（backend/services/browser_control.py）。 */
const USER_PAUSED_PREFIX = 'user_paused: ';
const USER_TAKEOVER_PREFIX = 'user_takeover: ';
/** 安全门禁的失败前缀（backend/tools/browser_tool.py，M4）。 */
const NEEDS_CONFIRMATION_PREFIX = 'needs_confirmation: ';
const HARD_BLOCKED_PREFIX = 'hard_blocked: ';
const SITE_BLOCKED_PREFIX = 'site_blocked: ';
const DENIED_BY_USER_PREFIX = 'denied_by_user: ';

/** 时间线最多展示的最近步骤数。 */
const MAX_STEPS = 8;
/** 控制状态 / 待确认项轮询间隔（毫秒）。 */
const POLL_INTERVAL_MS = 2000;
/** 审计默认拉取条数。 */
const AUDIT_LIMIT = 50;

type StepStatus =
  | 'pending'
  | 'success'
  | 'failed'
  | 'paused'
  | 'takeover'
  | 'waiting_confirmation'
  | 'blocked'
  | 'site_blocked'
  | 'denied';

const STEP_STATUS_LABEL: Record<StepStatus, TranslationKey> = {
  pending: 'browser.panel.steps.pending',
  success: 'browser.panel.steps.success',
  failed: 'browser.panel.steps.failed',
  paused: 'browser.panel.steps.paused',
  takeover: 'browser.panel.steps.takeover',
  waiting_confirmation: 'browser.panel.steps.waiting_confirmation',
  blocked: 'browser.panel.steps.blocked',
  site_blocked: 'browser.panel.steps.site_blocked',
  denied: 'browser.panel.steps.denied',
};

const STEP_STATUS_CLASS: Record<StepStatus, string> = {
  pending: 'text-text-secondary',
  success: 'text-success',
  failed: 'text-error',
  paused: 'text-warning',
  takeover: 'text-primary',
  waiting_confirmation: 'text-warning',
  blocked: 'text-error',
  site_blocked: 'text-error',
  denied: 'text-error',
};

/** 确认条按钮文案（按后端返回的 options 逐项渲染）。 */
const CONFIRM_OPTION_LABEL: Record<ConfirmationDecision, TranslationKey> = {
  session: 'browser.panel.confirm.option.session',
  always: 'browser.panel.confirm.option.always',
  approve: 'browser.panel.confirm.option.approve',
  deny: 'browser.panel.confirm.option.deny',
};

const CONTROL_LABEL: Record<BrowserControlState, TranslationKey> = {
  agent: 'browser.panel.status.agent',
  paused: 'browser.panel.status.paused',
  user_takeover: 'browser.panel.status.user_takeover',
};

const CONTROL_BADGE_CLASS: Record<BrowserControlState, string> = {
  agent: 'border-primary/40 text-primary',
  paused: 'border-warning/40 text-warning',
  user_takeover: 'border-success/40 text-success',
};

const CONTROL_BUTTONS: ReadonlyArray<{
  action: 'pause' | 'resume' | 'takeover' | 'return';
  labelKey: TranslationKey;
  testId: string;
}> = [
  { action: 'pause', labelKey: 'browser.panel.controls.pause', testId: 'browser-ai-pause' },
  { action: 'resume', labelKey: 'browser.panel.controls.resume', testId: 'browser-ai-resume' },
  {
    action: 'takeover',
    labelKey: 'browser.panel.controls.takeover',
    testId: 'browser-ai-takeover',
  },
  { action: 'return', labelKey: 'browser.panel.controls.return', testId: 'browser-ai-return' },
];

/**
 * 解析工具结果信封（``ToolResult.to_dict`` 的 JSON 字符串）。
 *
 * ``browser_meta`` 位于 ``content.browser_meta``；对结构缺失/非 JSON 保持
 * 静默降级（时间线仍展示原始工具名），不抛错。
 */
function parseEnvelope(call: ToolCall): StepEnvelope {
  if (!call.result) return EMPTY_ENVELOPE;
  try {
    const parsed = JSON.parse(call.result) as Record<string, unknown>;
    const content =
      parsed.content && typeof parsed.content === 'object'
        ? (parsed.content as Record<string, unknown>)
        : {};
    const rawMeta = content.browser_meta ?? parsed.browser_meta;
    const meta = rawMeta && typeof rawMeta === 'object' ? (rawMeta as BrowserStepMeta) : null;
    return {
      meta,
      success: typeof parsed.success === 'boolean' ? parsed.success : null,
      error: typeof parsed.error === 'string' ? parsed.error : '',
    };
  } catch {
    // 纯字符串错误（旧行为 / 工具层直接写 result）没有 browser_meta，
    // 但仍可能是 user_paused / needs_confirmation 等前缀状态：交给
    // stepStatus 按 error 前缀着色，而不是退化成「等待中」。
    return { meta: null, success: false, error: call.result };
  }
}

function stepStatus(envelope: StepEnvelope): StepStatus {
  if (envelope.error.startsWith(USER_PAUSED_PREFIX)) return 'paused';
  if (envelope.error.startsWith(USER_TAKEOVER_PREFIX)) return 'takeover';
  if (envelope.error.startsWith(NEEDS_CONFIRMATION_PREFIX)) return 'waiting_confirmation';
  if (envelope.error.startsWith(HARD_BLOCKED_PREFIX)) return 'blocked';
  if (envelope.error.startsWith(SITE_BLOCKED_PREFIX)) return 'site_blocked';
  if (envelope.error.startsWith(DENIED_BY_USER_PREFIX)) return 'denied';
  if (envelope.success === null) return 'pending';
  return envelope.success === true ? 'success' : 'failed';
}

function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

/** 审计时间：本地时区 HH:mm:ss。 */
function formatAuditTime(ts: number): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return '—';
  const pad = (value: number): string => String(value).padStart(2, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function stepAction(call: ToolCall, meta: BrowserStepMeta | null): string {
  return meta?.action || call.name.replace(/^browser_/, '');
}

function StepIcon({ action }: { action: string }): JSX.Element {
  const className = 'w-3 h-3 shrink-0 text-text-secondary';
  if (action === 'navigate') return <Globe className={className} />;
  if (action === 'interact') return <MousePointerClick className={className} />;
  if (action === 'snapshot') return <ScanEye className={className} />;
  return <Activity className={className} />;
}

/**
 * 右栏「浏览器」面板：控件在渲染层，页面本身由主进程 BrowserView 覆盖在
 * 占位区上方。bounds 通过 getBoundingClientRect 上报，主进程负责钳制。
 *
 * M3 起顶部增加「AI 操作」区：控制状态徽章、暂停/继续/接管/归还/定位窗口
 * 按钮，以及最近 browser_* 工具调用步骤时间线（数据来自 toolCalls 的
 * ``browser_meta``）。手动浏览工具栏与原 BrowserView 占位保持不变。
 */
export function BrowserPanel({
  toolCalls = [],
  sessionId: conversationId = null,
}: { toolCalls?: ToolCall[]; sessionId?: string | null } = {}): JSX.Element {
  const { t } = useI18n();
  const api = panelApi();
  const contentRef = useRef<HTMLDivElement | null>(null);
  const stepsRef = useRef<HTMLDivElement | null>(null);
  const inputFocused = useRef(false);
  const messages = useStore((s) => s.messages);
  const rememberedSessionId = useBrowserSessionStore((s) =>
    conversationId ? (s.byConversation[conversationId] ?? null) : null,
  );
  const [address, setAddress] = useState('');
  const [canBack, setCanBack] = useState(false);
  const [canForward, setCanForward] = useState(false);
  const [error, setError] = useState('');
  const [controlState, setControlState] = useState<BrowserControlState>('agent');
  const [controlBusy, setControlBusy] = useState(false);
  const [autoOpen, setAutoOpen] = useState(() => isBrowserPanelAutoOpenEnabled());
  const [pending, setPending] = useState<BrowserPendingConfirmation | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [shotFailed, setShotFailed] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditEntries, setAuditEntries] = useState<BrowserAuditEntry[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  /** 无 browser_meta 时从存活会话 / 无过滤确认项发现到的会话 id（C1c）。 */
  const [discoveredSessionId, setDiscoveredSessionId] = useState<string | null>(null);

  const reportBounds = useCallback(() => {
    const apiRef = panelApi();
    const element = contentRef.current;
    if (!apiRef || !element) return;
    const rect = element.getBoundingClientRect();
    void apiRef
      .setBounds({ x: rect.left, y: rect.top, width: rect.width, height: rect.height })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const apiRef = panelApi();
    if (!apiRef) return;
    void apiRef
      .show()
      .then(() => reportBounds())
      .catch(() => undefined);
    const observer = new ResizeObserver(() => reportBounds());
    if (contentRef.current) observer.observe(contentRef.current);
    window.addEventListener('resize', reportBounds);
    const interval = window.setInterval(() => {
      void apiRef
        .current()
        .then((state) => {
          if (!inputFocused.current) setAddress(state.url || '');
          setCanBack(state.canGoBack);
          setCanForward(state.canGoForward);
        })
        .catch(() => undefined);
    }, 1000);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', reportBounds);
      window.clearInterval(interval);
      void apiRef.hide().catch(() => undefined);
    };
  }, [reportBounds]);

  // C2：时间线数据源 = 持久化消息里的 tool_calls + 实时流式切片（去重、按序）。
  // step_done（finalizeStep）与 DONE（resetToolCalls）清空切片后，持久化
  // 消息里的浏览器步骤仍在，面板不会「闪一下就没」。
  const browserCalls = useMemo(() => {
    const persisted = collectPersistedBrowserCalls(messages, conversationId);
    const live = toolCalls.filter((call) => call.name.startsWith('browser_'));
    return mergeBrowserToolCalls(persisted, live);
  }, [messages, conversationId, toolCalls]);
  const recentCalls = browserCalls.slice(-MAX_STEPS);
  const toolSessionId = useMemo(() => latestBrowserSessionId(browserCalls), [browserCalls]);
  // 会话恢复：工具结果 → 本对话记忆 → 存活会话发现 → 待确认项自带 session。
  const sessionId =
    toolSessionId ?? rememberedSessionId ?? discoveredSessionId ?? pending?.session_id ?? null;

  // 切对话：清掉上一对话的瞬时发现态 / 旧确认条（会话记忆按对话键保留）。
  useEffect(() => {
    setDiscoveredSessionId(null);
    setPending(null);
    setControlState('agent');
  }, [conversationId]);

  // 首次拿到会话 id 即写入跨 stream 记忆，DONE 后仍能继续轮询。
  useEffect(() => {
    if (conversationId && sessionId) rememberBrowserSession(conversationId, sessionId);
  }, [conversationId, sessionId]);

  // 步骤追加时自动滚到底部（时间线固定高、可回溯）。
  useEffect(() => {
    const element = stepsRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [browserCalls.length]);

  // 控制状态 + 待确认项轮询（同一 2s 节奏、单个定时器）：失败静默
  // （后端未就绪/会话已回收都不该刷 toast）。
  useEffect(() => {
    const target = sessionId;
    let cancelled = false;
    const load = (): void => {
      if (!target) {
        // C1c：还没有任何 browser_meta 时也要能发现会话/待确认项 ——
        // 取唯一存活会话，并轮询无过滤确认项，避免首次确认永久卡死。
        void fetchBrowserControlSessions()
          .then((sessions) => {
            if (cancelled) return;
            const alive = sessions.filter((item) => item.alive);
            if (alive.length === 1) setDiscoveredSessionId(alive[0].session_id);
          })
          .catch(() => undefined);
        void fetchPendingConfirmations()
          .then((items) => {
            if (cancelled) return;
            const first = items[0] ?? null;
            setPending(first);
            if (first?.session_id) {
              setDiscoveredSessionId((prev) => prev ?? first.session_id);
            }
          })
          .catch(() => undefined);
        return;
      }
      void fetchBrowserControl(target)
        .then((state) => {
          if (!cancelled && state?.state) setControlState(state.state);
        })
        .catch(() => undefined);
      void fetchPendingConfirmations(target)
        .then((items) => {
          if (cancelled) return;
          if (items[0]) {
            setPending(items[0]);
            return;
          }
          // 会话过滤 0 条时回退到无过滤列表：session_id 推导错误时
          // pending 仍必须浮出（多会话场景也以实际待确认为准）。
          void fetchPendingConfirmations()
            .then((all) => {
              if (!cancelled) setPending(all[0] ?? null);
            })
            .catch(() => undefined);
        })
        .catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [sessionId]);

  // 截图加载失败时回退展示路径（截图位于数据目录，可能不在 sage-file 白名单内）。
  useEffect(() => {
    setShotFailed(false);
  }, [pending?.id]);

  // 审计按需加载：仅在用户展开 <details> 时拉取。
  useEffect(() => {
    if (!auditOpen || !sessionId) return;
    let cancelled = false;
    setAuditLoading(true);
    void fetchBrowserAudit(sessionId, AUDIT_LIMIT)
      .then((entries) => {
        if (!cancelled) setAuditEntries(entries);
      })
      .catch(() => {
        if (!cancelled) toast.error(t('browser.panel.audit.load_failed'));
      })
      .finally(() => {
        if (!cancelled) setAuditLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [auditOpen, sessionId, t]);

  const runControl = useCallback(
    async (
      action: 'pause' | 'resume' | 'takeover' | 'return',
      target: string,
    ): Promise<boolean> => {
      setControlBusy(true);
      try {
        const result = await setBrowserControl(target, action);
        if (result?.state) setControlState(result.state);
        return true;
      } catch {
        toast.error(t('browser.panel.ai.action_failed'));
        return false;
      } finally {
        setControlBusy(false);
      }
    },
    [t],
  );

  /** 请求主进程聚焦 agent 可见窗口；无头/无窗口时提示说明。 */
  const focusWindow = useCallback(
    async (target: string): Promise<void> => {
      const invoke = typeof window !== 'undefined' ? window.electronAPI?.invoke : undefined;
      if (!invoke) return;
      try {
        const result = await invoke<{ ok?: boolean }>('agent_browser_focus', {
          session: target,
        });
        if (!result?.ok) toast.info(t('browser.panel.ai.headless_hint'));
      } catch {
        toast.info(t('browser.panel.ai.headless_hint'));
      }
    },
    [t],
  );

  const handleControlClick = useCallback(
    (action: 'pause' | 'resume' | 'takeover' | 'return') => {
      if (!sessionId) return;
      void (async () => {
        const ok = await runControl(action, sessionId);
        // 接管成功后顺带把可见窗口带到前台，便于用户直接操作页面。
        if (ok && action === 'takeover') await focusWindow(sessionId);
      })();
    },
    [focusWindow, runControl, sessionId],
  );

  /** 提交确认裁决；成功后立即刷新控制状态与剩余待确认项。 */
  const handleResolve = useCallback(
    async (decision: ConfirmationDecision): Promise<void> => {
      const target = pending?.session_id || sessionId;
      if (!pending || !target) return;
      setConfirmBusy(true);
      try {
        const result = await resolveConfirmation(pending.id, decision);
        if (result?.control_state) setControlState(result.control_state);
        setPending(null);
        void fetchBrowserControl(target)
          .then((state) => {
            if (state?.state) setControlState(state.state);
          })
          .catch(() => undefined);
        void fetchPendingConfirmations(target)
          .then((items) => setPending(items[0] ?? null))
          .catch(() => undefined);
      } catch {
        toast.error(t('browser.panel.confirm.resolve_failed'));
      } finally {
        setConfirmBusy(false);
      }
    },
    [pending, sessionId, t],
  );

  const handleAutoOpenToggle = (checked: boolean): void => {
    setAutoOpen(checked);
    setBrowserPanelAutoOpenEnabled(checked);
  };

  const navigate = async (raw: string): Promise<void> => {
    const apiRef = panelApi();
    if (!apiRef) return;
    const url = raw.trim();
    if (!/^https?:\/\//i.test(url)) {
      setError(t('browser.panel.invalid_url'));
      return;
    }
    setError('');
    try {
      await apiRef.navigate(url);
      reportBounds();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (!api) {
    return (
      <div className="h-full flex items-center justify-center p-4 text-xs text-muted">
        {t('browser.panel.desktop_only')}
      </div>
    );
  }

  const controlsDisabled = !sessionId || controlBusy;

  return (
    <div className="h-full flex flex-col" data-testid="browser-panel">
      <section className="border-b border-border" data-testid="browser-ai-panel">
        <div className="flex items-center gap-1.5 px-2 pt-1.5">
          <span className="text-xs font-medium">{t('browser.panel.ai.title')}</span>
          <span
            role="status"
            data-testid="browser-ai-status"
            className={`px-1.5 py-0.5 rounded-radius-sm border text-ui-2xs shrink-0 ${
              CONTROL_BADGE_CLASS[controlState]
            }`}
          >
            {t(CONTROL_LABEL[controlState])}
          </span>
          <label className="ml-auto flex items-center gap-1 text-ui-2xs text-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={autoOpen}
              onChange={(event) => handleAutoOpenToggle(event.target.checked)}
              className="accent-primary"
              data-testid="browser-ai-auto-open"
            />
            {t('browser.panel.ai.auto_open')}
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-1 px-2 py-1.5">
          {CONTROL_BUTTONS.map(({ action, labelKey, testId }) => (
            <button
              key={action}
              type="button"
              aria-label={t(labelKey)}
              data-testid={testId}
              disabled={controlsDisabled}
              onClick={() => handleControlClick(action)}
              className="px-1.5 py-0.5 text-ui-2xs rounded-radius-sm border border-border hover:bg-bg-hover disabled:opacity-40"
            >
              {t(labelKey)}
            </button>
          ))}
          <button
            type="button"
            aria-label={t('browser.panel.controls.focus')}
            data-testid="browser-ai-focus"
            disabled={controlsDisabled}
            onClick={() => {
              if (sessionId) void focusWindow(sessionId);
            }}
            className="px-1.5 py-0.5 text-ui-2xs rounded-radius-sm border border-border hover:bg-bg-hover disabled:opacity-40"
          >
            {t('browser.panel.controls.focus')}
          </button>
        </div>
        {pending && (
          <div
            role="alertdialog"
            aria-labelledby="browser-confirm-title"
            data-testid="browser-confirm-bar"
            className="mx-2 mb-1.5 px-2 py-1.5 rounded-radius-sm border border-warning/40 bg-warning/5"
          >
            <p id="browser-confirm-title" className="text-ui-2xs font-medium text-text">
              {pending.kind === 'site_access'
                ? t('browser.panel.confirm.site_title').replace('{domain}', pending.domain || '—')
                : t('browser.panel.confirm.action_title').replace(
                    '{description}',
                    pending.description || '—',
                  )}
            </p>
            {pending.description && pending.kind === 'site_access' && (
              <p className="mt-0.5 text-ui-2xs text-text-secondary">{pending.description}</p>
            )}
            {pending.thumbnail_data_url ? (
              // I4：后端内联的有界缩略图（数据目录不在 sage-file 白名单内）
              <img
                data-testid="browser-confirm-shot"
                src={pending.thumbnail_data_url}
                alt={t('browser.panel.confirm.screenshot_alt')}
                className="mt-1 max-h-24 rounded-radius-sm border border-border object-contain"
              />
            ) : pending.screenshot_path ? (
              shotFailed ? (
                <p
                  data-testid="browser-confirm-shot-path"
                  className="mt-0.5 truncate font-mono text-ui-2xs text-muted"
                  title={pending.screenshot_path}
                >
                  {pending.screenshot_path}
                </p>
              ) : (
                <img
                  data-testid="browser-confirm-shot"
                  src={buildLocalImageSrc(pending.screenshot_path)}
                  alt={t('browser.panel.confirm.screenshot_alt')}
                  onError={() => setShotFailed(true)}
                  className="mt-1 max-h-24 rounded-radius-sm border border-border object-contain"
                />
              )
            ) : null}
            <div className="mt-1 flex flex-wrap gap-1">
              {pending.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  data-testid={`browser-confirm-option-${option}`}
                  disabled={confirmBusy}
                  onClick={() => void handleResolve(option)}
                  className="px-1.5 py-0.5 text-ui-2xs rounded-radius-sm border border-border hover:bg-bg-hover disabled:opacity-40"
                >
                  {t(CONFIRM_OPTION_LABEL[option])}
                </button>
              ))}
            </div>
          </div>
        )}
        <div
          ref={stepsRef}
          data-testid="browser-ai-steps"
          className="max-h-40 overflow-y-auto px-2 pb-1.5"
        >
          {recentCalls.length === 0 ? (
            <p className="text-ui-2xs text-muted py-1">{t('browser.panel.ai.waiting')}</p>
          ) : (
            recentCalls.map((call, index) => {
              const envelope = parseEnvelope(call);
              const action = stepAction(call, envelope.meta);
              const status = stepStatus(envelope);
              let summary: string;
              if (action === 'navigate') {
                summary = t('browser.panel.steps.navigate').replace(
                  '{url}',
                  String(envelope.meta?.url || call.args?.url || '—'),
                );
              } else if (action === 'interact') {
                const name = String(
                  envelope.meta?.target_name ||
                    call.args?.text ||
                    call.args?.selector ||
                    call.args?.ref ||
                    '',
                );
                const key = name
                  ? ('browser.panel.steps.interact' as const)
                  : ('browser.panel.steps.interact_default' as const);
                summary = t(key).replace('{name}', name);
              } else if (action === 'snapshot') {
                summary = t('browser.panel.steps.snapshot');
              } else {
                summary = call.name.replace(/^browser_/, '');
              }
              const screenshot = envelope.meta?.screenshot_path || '';
              return (
                <div
                  key={call.id ?? `${action}-${index}`}
                  data-testid={`browser-ai-step-${index}`}
                  className="flex items-center gap-1.5 py-0.5 text-ui-2xs"
                >
                  <StepIcon action={action} />
                  <span className="flex-1 min-w-0 truncate" title={summary}>
                    {summary}
                  </span>
                  {screenshot && (
                    <span
                      data-testid={`browser-ai-step-thumb-${index}`}
                      className="flex items-center gap-0.5 text-muted shrink-0"
                      title={screenshot}
                    >
                      <Camera className="w-3 h-3" />
                      {baseName(screenshot)}
                    </span>
                  )}
                  <span className={`shrink-0 ${STEP_STATUS_CLASS[status]}`}>
                    {t(STEP_STATUS_LABEL[status])}
                  </span>
                </div>
              );
            })
          )}
        </div>
        <details
          data-testid="browser-ai-audit"
          className="px-2 pb-1.5"
          onToggle={(event) => setAuditOpen(event.currentTarget.open)}
        >
          <summary className="cursor-pointer select-none text-ui-2xs text-text-secondary">
            {t('browser.panel.audit.title')}
          </summary>
          {auditLoading ? (
            <p className="py-1 text-ui-2xs text-muted">{t('browser.panel.audit.loading')}</p>
          ) : auditEntries.length === 0 ? (
            <p className="py-1 text-ui-2xs text-muted">{t('browser.panel.audit.empty')}</p>
          ) : (
            <table className="mt-1 w-full text-ui-2xs">
              <thead>
                <tr className="text-left text-muted">
                  <th className="py-0.5 pr-1 font-normal">{t('browser.panel.audit.time')}</th>
                  <th className="py-0.5 pr-1 font-normal">{t('browser.panel.audit.action')}</th>
                  <th className="py-0.5 pr-1 font-normal">{t('browser.panel.audit.target')}</th>
                  <th className="py-0.5 pr-1 font-normal">{t('browser.panel.audit.result')}</th>
                  <th className="py-0.5 font-normal">{t('browser.panel.audit.approval')}</th>
                </tr>
              </thead>
              <tbody>
                {auditEntries.map((entry) => (
                  <tr key={entry.id} data-testid={`browser-audit-row-${entry.id}`}>
                    <td className="whitespace-nowrap py-0.5 pr-1">{formatAuditTime(entry.ts)}</td>
                    <td className="py-0.5 pr-1">{entry.action || '—'}</td>
                    <td
                      className="max-w-[10rem] truncate py-0.5 pr-1"
                      title={entry.target_desc || entry.target_ref || entry.domain}
                    >
                      {entry.target_desc || entry.target_ref || entry.domain || '—'}
                    </td>
                    <td className="py-0.5 pr-1">{entry.result || '—'}</td>
                    <td className="py-0.5">{entry.approval || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </details>
      </section>
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-border">
        <button
          type="button"
          aria-label={t('browser.panel.back')}
          className="p-1 rounded hover:bg-bg-hover disabled:opacity-40"
          disabled={!canBack}
          onClick={() => void api.back().catch(() => undefined)}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          aria-label={t('browser.panel.forward')}
          className="p-1 rounded hover:bg-bg-hover disabled:opacity-40"
          disabled={!canForward}
          onClick={() => void api.forward().catch(() => undefined)}
        >
          <ArrowRight className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          aria-label={t('browser.panel.reload')}
          className="p-1 rounded hover:bg-bg-hover"
          onClick={() => void api.reload().catch(() => undefined)}
        >
          <RotateCw className="w-3.5 h-3.5" />
        </button>
        <Globe className="w-3.5 h-3.5 text-text-secondary shrink-0" />
        <input
          data-testid="browser-panel-address"
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          onFocus={() => {
            inputFocused.current = true;
          }}
          onBlur={() => {
            inputFocused.current = false;
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void navigate(address);
          }}
          placeholder={t('browser.panel.placeholder')}
          className="flex-1 min-w-0 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
        />
      </div>
      {error && <div className="px-2 py-1 text-xs text-error">{error}</div>}
      <div ref={contentRef} className="flex-1 min-h-0 bg-bg" data-testid="browser-panel-content" />
    </div>
  );
}
