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
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import {
  fetchBrowserControl,
  setBrowserControl,
  type BrowserControlState,
} from '../../shared/api/browserControlClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import type { ToolCall } from '../../shared/lib/store';
import {
  isBrowserPanelAutoOpenEnabled,
  setBrowserPanelAutoOpenEnabled,
} from '../right-panel/rightPanelStore';

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

/** 时间线最多展示的最近步骤数。 */
const MAX_STEPS = 8;
/** 控制状态轮询间隔（毫秒）。 */
const POLL_INTERVAL_MS = 2000;

type StepStatus = 'pending' | 'success' | 'failed' | 'paused' | 'takeover';

const STEP_STATUS_LABEL: Record<StepStatus, TranslationKey> = {
  pending: 'browser.panel.steps.pending',
  success: 'browser.panel.steps.success',
  failed: 'browser.panel.steps.failed',
  paused: 'browser.panel.steps.paused',
  takeover: 'browser.panel.steps.takeover',
};

const STEP_STATUS_CLASS: Record<StepStatus, string> = {
  pending: 'text-text-secondary',
  success: 'text-success',
  failed: 'text-error',
  paused: 'text-warning',
  takeover: 'text-primary',
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
    return EMPTY_ENVELOPE;
  }
}

function stepStatus(envelope: StepEnvelope): StepStatus {
  if (envelope.error.startsWith(USER_PAUSED_PREFIX)) return 'paused';
  if (envelope.error.startsWith(USER_TAKEOVER_PREFIX)) return 'takeover';
  if (envelope.success === null) return 'pending';
  return envelope.success === true ? 'success' : 'failed';
}

function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
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
export function BrowserPanel({ toolCalls = [] }: { toolCalls?: ToolCall[] } = {}): JSX.Element {
  const { t } = useI18n();
  const api = panelApi();
  const contentRef = useRef<HTMLDivElement | null>(null);
  const stepsRef = useRef<HTMLDivElement | null>(null);
  const inputFocused = useRef(false);
  const [address, setAddress] = useState('');
  const [canBack, setCanBack] = useState(false);
  const [canForward, setCanForward] = useState(false);
  const [error, setError] = useState('');
  const [controlState, setControlState] = useState<BrowserControlState>('agent');
  const [controlBusy, setControlBusy] = useState(false);
  const [autoOpen, setAutoOpen] = useState(() => isBrowserPanelAutoOpenEnabled());

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

  // AI 步骤只取浏览器工具调用；会话 id 取最近一条带 browser_meta.session_id 的。
  const browserCalls = toolCalls.filter((call) => call.name.startsWith('browser_'));
  const recentCalls = browserCalls.slice(-MAX_STEPS);
  let sessionId: string | null = null;
  for (let i = browserCalls.length - 1; i >= 0; i -= 1) {
    const meta = parseEnvelope(browserCalls[i]).meta;
    if (meta?.session_id) {
      sessionId = meta.session_id;
      break;
    }
  }

  // 步骤追加时自动滚到底部（时间线固定高、可回溯）。
  useEffect(() => {
    const element = stepsRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [browserCalls.length]);

  // 控制状态轮询：失败静默（后端未就绪/会话已回收都不该刷 toast）。
  useEffect(() => {
    const target = sessionId;
    if (!target) {
      setControlState('agent');
      return;
    }
    let cancelled = false;
    const load = () => {
      void fetchBrowserControl(target)
        .then((state) => {
          if (!cancelled && state?.state) setControlState(state.state);
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
