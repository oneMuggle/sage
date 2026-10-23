/**
 * Out-of-process plugin runtime controls and detail panel (R83).
 *
 * Kept separate from PluginsTab so the settings tab remains below the
 * architecture file-size limit. Runtime state is intentionally distinct from
 * the persisted lifecycle record state.
 */
import { clsx } from 'clsx';
import { useEffect, useMemo, useState } from 'react';

import type {
  PluginRecord,
  PluginRuntimeState,
  PluginRuntimeStatus,
} from '../../shared/api/pluginClient';

export type PluginRuntimeAction = 'start' | 'stop' | 'restart';

const RUNTIME_BADGE_CLASSES: Record<PluginRuntimeState, string> = {
  pending: 'bg-faint/15 text-faint',
  loading: 'bg-warning/15 text-warning',
  active: 'bg-success/15 text-success',
  failed: 'bg-error/15 text-error',
  unloading: 'bg-warning/15 text-warning',
  disposed: 'bg-faint/15 text-faint',
};

function runtimeStateLabel(state: PluginRuntimeState, en: boolean): string {
  const labels: Record<PluginRuntimeState, string> = en
    ? {
        pending: 'Not started',
        loading: 'Starting',
        active: 'Running',
        failed: 'Failed',
        unloading: 'Stopping',
        disposed: 'Stopped',
      }
    : {
        pending: '未启动',
        loading: '启动中',
        active: '运行中',
        failed: '失败',
        unloading: '停止中',
        disposed: '已停止',
      };
  return labels[state] ?? state;
}

export function RuntimeStateBadge({
  runtime,
  en,
  testId,
}: {
  runtime: PluginRuntimeStatus;
  en: boolean;
  testId?: string;
}) {
  return (
    <span
      data-testid={testId}
      className={clsx(
        'rounded-full px-2 py-0.5 text-ui-2xs font-medium',
        RUNTIME_BADGE_CLASSES[runtime.state],
      )}
    >
      {en ? 'Runtime: ' : '运行：'}
      {runtimeStateLabel(runtime.state, en)}
    </span>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatRuntimeTime(value: number | null): string {
  if (value == null) return '—';
  const date = new Date(value * 1000);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatMiB(bytes: number): string {
  return `${Math.round(bytes / 1024 / 1024)} MiB`;
}

export function PluginRuntimeControls({
  plugin,
  en,
  busy,
  onAction,
}: {
  plugin: PluginRecord;
  en: boolean;
  busy: boolean;
  onAction: (plugin: PluginRecord, action: PluginRuntimeAction) => Promise<void> | void;
}) {
  const runtime = plugin.runtime;
  if (!runtime) return null;

  const running = runtime.state === 'active';
  const canStart = plugin.status === 'enabled' && !running;
  const buttonClass =
    'rounded-radius-sm border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50';

  return (
    <>
      {running ? (
        <>
          <button
            type="button"
            data-testid={`plugin-runtime-stop-${plugin.name}`}
            className={clsx(buttonClass, 'border-warning/40 text-warning hover:bg-warning/10')}
            disabled={busy}
            onClick={() => void onAction(plugin, 'stop')}
          >
            {en ? 'Stop runtime' : '停止运行'}
          </button>
          <button
            type="button"
            data-testid={`plugin-runtime-restart-${plugin.name}`}
            className={clsx(buttonClass, 'border-primary/40 text-primary hover:bg-primary/10')}
            disabled={busy}
            onClick={() => void onAction(plugin, 'restart')}
          >
            {en ? 'Restart' : '重启'}
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            data-testid={`plugin-runtime-start-${plugin.name}`}
            className={clsx(buttonClass, 'border-success/40 text-success hover:bg-success/10')}
            disabled={busy || !canStart}
            onClick={() => void onAction(plugin, 'start')}
          >
            {en ? 'Start runtime' : '启动运行'}
          </button>
          {runtime.state === 'failed' && (
            <button
              type="button"
              data-testid={`plugin-runtime-restart-${plugin.name}`}
              className={clsx(buttonClass, 'border-primary/40 text-primary hover:bg-primary/10')}
              disabled={busy || plugin.status !== 'enabled'}
              onClick={() => void onAction(plugin, 'restart')}
            >
              {en ? 'Restart' : '重启'}
            </button>
          )}
        </>
      )}
    </>
  );
}

export function PluginRuntimePanel({
  plugin,
  en,
  onInvoke,
}: {
  plugin: PluginRecord;
  en: boolean;
  onInvoke: (
    plugin: PluginRecord,
    capability: string,
    args: Record<string, unknown>,
  ) => Promise<unknown>;
}) {
  const runtime = plugin.runtime;
  const capabilities = useMemo(() => {
    if (runtime?.capabilities.length) return runtime.capabilities;
    return (plugin.manifest.capabilities ?? [])
      .filter((capability) => capability.type === 'tool' && capability.entry_point)
      .map((capability) => capability.name);
  }, [plugin.manifest.capabilities, runtime?.capabilities]);

  const [capability, setCapability] = useState('');
  const [argsText, setArgsText] = useState('{}');
  const [resultText, setResultText] = useState<string | null>(null);
  const [invokeError, setInvokeError] = useState<string | null>(null);
  const [invoking, setInvoking] = useState(false);

  useEffect(() => {
    setCapability((current) => (capabilities.includes(current) ? current : (capabilities[0] ?? '')));
  }, [capabilities]);

  useEffect(() => {
    setResultText(null);
    setInvokeError(null);
  }, [plugin.name]);

  if (!runtime) return null;

  const copy = {
    title: en ? 'Out-of-process runtime' : '进程外运行',
    pid: 'PID',
    restarts: en ? 'Restarts' : '重启次数',
    started: en ? 'Started' : '启动于',
    capabilities: en ? 'Loaded tools' : '已加载工具',
    none: en ? 'None' : '无',
    lastError: en ? 'Last error' : '最近错误',
    limits: en ? 'Limits' : '资源上限',
    memory: en ? 'memory' : '内存',
    request: en ? 'request' : '单次调用',
    enforced: en ? 'enforced' : '已强制',
    notEnforced: en ? 'not OS-enforced' : '未由 OS 强制',
    stderr: en ? 'Worker stderr (tail)' : 'Worker stderr（尾部）',
    capability: en ? 'Tool capability' : '工具能力',
    args: en ? 'Arguments JSON' : '参数 JSON',
    invoke: en ? 'Invoke tool' : '调用工具',
    invoking: en ? 'Invoking…' : '调用中…',
    result: en ? 'Result' : '结果',
    argsInvalid: en ? 'Arguments must be a JSON object.' : '参数必须是 JSON 对象。',
    startFirst: en ? 'Start the runtime before invoking a tool.' : '调用工具前请先启动运行进程。',
    noTools: en ? 'No hostable tool capabilities.' : '没有可托管的 tool 能力。',
  };

  const handleInvoke = async (): Promise<void> => {
    let args: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(argsText);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error(copy.argsInvalid);
      }
      args = parsed as Record<string, unknown>;
    } catch (error) {
      setInvokeError(errorMessage(error));
      setResultText(null);
      return;
    }

    setInvoking(true);
    setInvokeError(null);
    try {
      const result = await onInvoke(plugin, capability, args);
      setResultText(JSON.stringify(result, null, 2) ?? 'null');
    } catch (error) {
      setInvokeError(errorMessage(error));
      setResultText(null);
    } finally {
      setInvoking(false);
    }
  };

  return (
    <section data-testid={`plugin-runtime-panel-${plugin.name}`} className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h5 className="text-xs font-semibold text-text">{copy.title}</h5>
        <RuntimeStateBadge runtime={runtime} en={en} />
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted">{copy.pid}</dt>
        <dd className="font-mono text-text">{runtime.pid ?? '—'}</dd>
        <dt className="text-muted">{copy.restarts}</dt>
        <dd className="text-text">{runtime.restart_count}</dd>
        <dt className="text-muted">{copy.started}</dt>
        <dd className="text-text">{formatRuntimeTime(runtime.started_at)}</dd>
        <dt className="text-muted">{copy.capabilities}</dt>
        <dd className="font-mono text-text">
          {capabilities.length ? capabilities.join(', ') : copy.none}
        </dd>
        <dt className="text-muted">{copy.limits}</dt>
        <dd className="text-text">
          {copy.memory} {formatMiB(runtime.limits.memory_bytes)} (
          {runtime.limits.memory_limit_enforced ? copy.enforced : copy.notEnforced}) · {copy.request}{' '}
          {runtime.limits.request_timeout_seconds}s
        </dd>
        {runtime.last_error && (
          <>
            <dt className="text-muted">{copy.lastError}</dt>
            <dd className="break-words text-error">{runtime.last_error}</dd>
          </>
        )}
      </dl>

      {runtime.stderr_tail && (
        <div>
          <h6 className="mb-1 text-ui-2xs font-medium text-muted">{copy.stderr}</h6>
          <pre
            data-testid={`plugin-runtime-stderr-${plugin.name}`}
            className="max-h-32 overflow-auto whitespace-pre-wrap rounded-radius-sm bg-black/20 px-2 py-1 font-mono text-ui-2xs text-muted"
          >
            {runtime.stderr_tail}
          </pre>
        </div>
      )}

      {capabilities.length === 0 ? (
        <p className="text-xs text-muted">{copy.noTools}</p>
      ) : (
        <div className="space-y-2">
          <label className="block space-y-1 text-xs text-muted">
            <span>{copy.capability}</span>
            <select
              data-testid={`plugin-invoke-capability-${plugin.name}`}
              value={capability}
              onChange={(event) => setCapability(event.target.value)}
              className="w-full rounded-radius-sm border border-border bg-surface px-2 py-1 text-xs text-text"
            >
              {capabilities.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 text-xs text-muted">
            <span>{copy.args}</span>
            <textarea
              data-testid={`plugin-invoke-args-${plugin.name}`}
              value={argsText}
              onChange={(event) => setArgsText(event.target.value)}
              rows={4}
              spellCheck={false}
              className="w-full rounded-radius-sm border border-border bg-surface px-2 py-1 font-mono text-xs text-text"
            />
          </label>
          {!runtime.running && <p className="text-xs text-muted">{copy.startFirst}</p>}
          <button
            type="button"
            data-testid={`plugin-invoke-${plugin.name}`}
            className="rounded-radius-sm bg-primary px-3 py-1.5 text-xs text-text-inverse hover:bg-primary-hover disabled:opacity-50"
            disabled={!runtime.running || !capability || invoking}
            onClick={() => void handleInvoke()}
          >
            {invoking ? copy.invoking : copy.invoke}
          </button>
          {invokeError && (
            <div role="alert" className="text-xs text-error">
              {invokeError}
            </div>
          )}
          {resultText !== null && (
            <div>
              <h6 className="mb-1 text-ui-2xs font-medium text-muted">{copy.result}</h6>
              <pre
                data-testid={`plugin-invoke-result-${plugin.name}`}
                className="max-h-40 overflow-auto whitespace-pre-wrap rounded-radius-sm bg-black/20 px-2 py-1 font-mono text-xs text-text"
              >
                {resultText}
              </pre>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
