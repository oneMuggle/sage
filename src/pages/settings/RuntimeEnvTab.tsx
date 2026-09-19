/**
 * Settings 页面 - 开发环境 Tab
 *
 * 展示本机可用运行时 + 当前项目诊断结果，并提供一个"试跑"输入框让用户
 * 通过 runtime_exec 验证选定的运行时确实可用。
 *
 * 设计原则:
 * - 进入 tab 自动探测一次 (useEffect)，避免用户每次手动点按钮
 * - runtime_exec 是 EXEC 操作，默认 deny，需要 PermissionEnforcer 批准；
 *   UI 上明确告知用户"执行需要批准"
 * - 所有 API 调用通过 Electron IPC bridge (runtimeApi)，与后端 REST 解耦
 */

import { useCallback, useEffect, useState } from 'react';

import { runtimeApi } from '../../shared/api/runtimeApi';
import type {
  Diagnostic,
  ExecutionResult,
  ProbeResult,
  ProjectDiagnosis,
  RuntimeInfo,
  ToolCallEnvelope,
} from '../../shared/api/runtimeTypes';

import { SettingRow } from './components';

type ProbeState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ok'; data: ProbeResult };

type DiagnoseState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ok'; data: ProjectDiagnosis };

/** Exec 输出视图 —— 前端渲染用的字段集合，与后端 ``ExecutionResult`` 镜像
 *  但 key 用 camelCase 贴合 React 习惯。成功与失败路径都复用同一类型，
 *  因为子进程失败时后端同样会返回结构化的 ExecutionResult（含 stdout/stderr/
 *  error/timed_out），前端需要这些字段做诊断。
 */
interface ExecResultView {
  stdout: string;
  stderr: string;
  exitCode: number | null;
  timedOut: boolean;
  duration: number;
  error: string | null;
  outputTruncated: boolean;
  command: string[] | null;
}

type ExecState =
  | { kind: 'idle' }
  | { kind: 'running' }
  | { kind: 'error'; message: string; result?: ExecResultView }
  | { kind: 'denied'; message: string }
  | { kind: 'success'; result: ExecResultView };

function toView(r: ExecutionResult): ExecResultView {
  return {
    stdout: r.stdout,
    stderr: r.stderr,
    exitCode: r.exit_code,
    timedOut: r.timed_out,
    duration: r.duration_seconds,
    error: r.error,
    outputTruncated: r.output_truncated,
    command: r.command,
  };
}

export function RuntimeEnvTab() {
  const [probe, setProbe] = useState<ProbeState>({ kind: 'idle' });
  const [diagnose, setDiagnose] = useState<DiagnoseState>({ kind: 'idle' });
  const [exec, setExec] = useState<ExecState>({ kind: 'idle' });
  const [selectedRuntime, setSelectedRuntime] = useState<string | null>(null);
  const [code, setCode] = useState('print("hello from Sage runtime assistant")');

  const runProbe = useCallback(async () => {
    setProbe({ kind: 'loading' });
    try {
      const env = await runtimeApi.probe();
      if (env.success && env.output) {
        setProbe({ kind: 'ok', data: env.output });
        // 默认选中推荐的运行时
        if (env.output.recommended && !selectedRuntime) {
          setSelectedRuntime(env.output.recommended);
        }
      } else {
        setProbe({ kind: 'error', message: env.error ?? '探测失败' });
      }
    } catch (error) {
      setProbe({
        kind: 'error',
        message: error instanceof Error ? error.message : '探测请求失败',
      });
    }
  }, [selectedRuntime]);

  const runDiagnose = useCallback(async () => {
    setDiagnose({ kind: 'loading' });
    try {
      const env = await runtimeApi.diagnose();
      if (env.success && env.output) {
        setDiagnose({ kind: 'ok', data: env.output });
      } else {
        setDiagnose({ kind: 'error', message: env.error ?? '诊断失败' });
      }
    } catch (error) {
      setDiagnose({
        kind: 'error',
        message: error instanceof Error ? error.message : '诊断请求失败',
      });
    }
  }, []);

  const runExec = useCallback(async () => {
    if (!selectedRuntime) return;
    setExec({ kind: 'running' });
    const env = await runtimeApi.probe();
    if (!env.success || !env.output) {
      setExec({ kind: 'error', message: env.error ?? '无法确定语言' });
      return;
    }
    // 找到匹配的运行时的语言
    const rt = env.output.runtimes.find((r) => r.path === selectedRuntime);
    const language = rt?.language ?? 'python';
    try {
      const result = await runtimeApi.exec({
        language,
        runtime_path: selectedRuntime,
        code,
      });
      handleExecResult(result);
    } catch (error) {
      setExec({
        kind: 'error',
        message: error instanceof Error ? error.message : '执行请求失败',
      });
    }
  }, [selectedRuntime, code]);

  function handleExecResult(result: ToolCallEnvelope<ExecutionResult>) {
    if (result.success && result.output) {
      setExec({ kind: 'success', result: toView(result.output) });
      return;
    }
    // 权限拒绝 vs 其他失败
    const err = result.error ?? '执行失败';
    if (err.includes('权限') || err.includes('Permission') || err.includes('denied')) {
      setExec({ kind: 'denied', message: err });
      return;
    }
    // 子进程失败（exit_code!=0 / spawn 失败 / 超时）—— 后端 success=false，
    // 但 output 仍携带结构化的 ExecutionResult，含 error/timed_out/stdout/
    // stderr，前端需要展示这些诊断字段而不是只显示一个笼统的「执行失败」。
    const subprocess = result.output ? toView(result.output) : undefined;
    setExec({ kind: 'error', message: err, result: subprocess });
  }

  // 进入 tab 自动探测一次
  useEffect(() => {
    runProbe();
    runDiagnose();
  }, [runProbe, runDiagnose]);

  return (
    <div className="space-y-6">
      <section>
        <div className="mb-3">
          <h3 className="text-[15px] font-semibold text-ink">本机运行时</h3>
          <p className="text-xs text-muted mt-1">
            自动发现 Python、Node.js 等运行时。仅只读探测，不触发执行。
          </p>
        </div>
        <ProbePanel state={probe} onRetry={runProbe} />
      </section>

      <section>
        <div className="mb-3">
          <h3 className="text-[15px] font-semibold text-ink">项目诊断</h3>
          <p className="text-xs text-muted mt-1">
            根据工作区推断项目类型，比对所需运行时是否齐备。
          </p>
        </div>
        <DiagnosePanel state={diagnose} onRetry={runDiagnose} />
      </section>

      <section>
        <SettingRow
          label="试跑代码片段"
          desc="在选定的运行时里执行一段代码。需要用户批准（与 Bash 工具同样的审批闸口）。"
        >
          <ExecPanel
            state={exec}
            runtimes={probe.kind === 'ok' ? probe.data.runtimes : []}
            selectedRuntime={selectedRuntime}
            onSelectRuntime={setSelectedRuntime}
            code={code}
            onChangeCode={setCode}
            onRun={runExec}
          />
        </SettingRow>
      </section>
    </div>
  );
}

function ProbePanel({ state, onRetry }: { state: ProbeState; onRetry: () => void }) {
  if (state.kind === 'loading') {
    return <div className="text-sm text-muted">正在探测…</div>;
  }
  if (state.kind === 'error') {
    return (
      <div className="space-y-2">
        <div className="text-sm text-red-600">探测失败: {state.message}</div>
        <button
          type="button"
          className="px-3 py-1 text-xs bg-primary text-text-inverse rounded"
          onClick={onRetry}
        >
          重试
        </button>
      </div>
    );
  }
  if (state.kind === 'idle') {
    return <div className="text-sm text-muted">等待探测…</div>;
  }
  const { data } = state;
  if (data.runtimes.length === 0) {
    return (
      <div className="text-sm text-muted">
        未探测到任何运行时。{data.errors.length > 0 && `错误: ${data.errors.join(', ')}`}
      </div>
    );
  }
  // 按语言分组
  const grouped: Record<string, RuntimeInfo[]> = {};
  for (const r of data.runtimes) {
    (grouped[r.language] ??= []).push(r);
  }
  return (
    <ul className="space-y-2">
      {Object.entries(grouped).map(([lang, items]) => (
        <li key={lang}>
          <div className="text-xs uppercase tracking-wide text-muted">{lang}</div>
          <ul className="mt-1 space-y-1">
            {items.map((rt) => (
              <li key={rt.path} className="flex items-baseline gap-2 text-sm text-ink">
                <span className={rt.is_default ? 'font-semibold text-primary' : 'text-muted'}>
                  {rt.version ?? '(未知版本)'}
                </span>
                <span className="text-xs text-muted font-mono">{rt.path}</span>
                {rt.is_default && (
                  <span className="text-[10px] px-1 py-0.5 rounded bg-primary/10 text-primary">
                    推荐
                  </span>
                )}
                <span className="text-[10px] text-muted">{rt.source}</span>
              </li>
            ))}
          </ul>
        </li>
      ))}
      {data.errors.length > 0 && (
        <li className="text-xs text-amber-600">警告: {data.errors.join('; ')}</li>
      )}
    </ul>
  );
}

function DiagnosePanel({ state, onRetry }: { state: DiagnoseState; onRetry: () => void }) {
  if (state.kind === 'loading') {
    return <div className="text-sm text-muted">正在诊断…</div>;
  }
  if (state.kind === 'error') {
    return (
      <div className="space-y-2">
        <div className="text-sm text-red-600">诊断失败: {state.message}</div>
        <button
          type="button"
          className="px-3 py-1 text-xs bg-primary text-text-inverse rounded"
          onClick={onRetry}
        >
          重试
        </button>
      </div>
    );
  }
  if (state.kind === 'idle') {
    return <div className="text-sm text-muted">等待诊断…</div>;
  }
  const { data } = state;
  const manifests = Array.isArray(data.manifests) ? data.manifests : [];
  const diagnostics = Array.isArray(data.diagnostics) ? data.diagnostics : [];
  const probeErrors = Array.isArray(data.probe_errors) ? data.probe_errors : [];
  const requiredLanguages = [...new Set(manifests.map((manifest) => manifest.language))];
  const levelLabel =
    {
      satisfied: '✓ 全部满足',
      partial: '⚠ 部分满足',
      unsatisfied: '✕ 未满足',
    }[data.level] ?? '未知等级';
  const levelClassName =
    {
      satisfied: 'text-green-600',
      partial: 'text-amber-600',
      unsatisfied: 'text-red-600',
    }[data.level] ?? 'text-muted';
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted">项目清单:</span>
        <span className="font-mono">
          {manifests.length > 0 ? requiredLanguages.join(', ') : '未识别'}
        </span>
        <span className="text-muted ml-4">满足度:</span>
        <span className={`${levelClassName} font-semibold`}>{levelLabel}</span>
      </div>
      {data.recommended_runtime && (
        <div className="text-xs text-muted">推荐运行时: {data.recommended_runtime}</div>
      )}
      {requiredLanguages.length > 0 && (
        <div className="text-xs text-muted">需要的语言: {requiredLanguages.join(', ')}</div>
      )}
      {diagnostics.length > 0 && (
        <ul className="space-y-1">
          {diagnostics.map((d: Diagnostic, i: number) => (
            <li key={i} className="text-sm">
              <SeverityBadge severity={d.severity} />
              <span className="ml-2 font-mono text-xs text-muted">{d.code}</span>
              <span className="ml-2">{d.message}</span>
              {d.remediation && <span className="ml-2 text-xs text-primary">{d.remediation}</span>}
            </li>
          ))}
        </ul>
      )}
      {probeErrors.length > 0 && (
        <div className="text-xs text-amber-600">探测警告: {probeErrors.join('; ')}</div>
      )}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: Diagnostic['severity'] }) {
  const styles: Record<'info' | 'warning' | 'error', string> = {
    info: 'bg-blue-100 text-blue-700',
    warning: 'bg-amber-100 text-amber-700',
    error: 'bg-red-100 text-red-700',
  };
  const fallback = 'bg-bg-muted text-muted';
  return (
    <span
      className={`inline-block px-1.5 py-0.5 text-[10px] rounded uppercase font-semibold ${
        styles[severity as 'info' | 'warning' | 'error'] ?? fallback
      }`}
    >
      {severity}
    </span>
  );
}

interface ExecPanelProps {
  state: ExecState;
  runtimes: RuntimeInfo[];
  selectedRuntime: string | null;
  onSelectRuntime: (path: string) => void;
  code: string;
  onChangeCode: (value: string) => void;
  onRun: () => void;
}

function ExecPanel({
  state,
  runtimes,
  selectedRuntime,
  onSelectRuntime,
  code,
  onChangeCode,
  onRun,
}: ExecPanelProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <label className="text-xs text-muted">运行时:</label>
        <select
          value={selectedRuntime ?? ''}
          onChange={(e) => onSelectRuntime(e.target.value)}
          className="flex-1 text-sm px-2 py-1 border border-line rounded bg-bg"
        >
          <option value="" disabled>
            {runtimes.length === 0 ? '先运行探测' : '选择运行时…'}
          </option>
          {runtimes.map((rt) => (
            <option key={rt.path} value={rt.path}>
              {rt.language} {rt.version} — {rt.path}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="px-3 py-1 text-xs bg-primary text-text-inverse rounded disabled:opacity-50"
          disabled={!selectedRuntime || state.kind === 'running'}
          onClick={onRun}
        >
          {state.kind === 'running' ? '执行中…' : '执行'}
        </button>
      </div>
      <textarea
        value={code}
        onChange={(e) => onChangeCode(e.target.value)}
        className="w-full h-28 text-xs font-mono px-2 py-1 border border-line rounded bg-bg"
        placeholder="输入要执行的代码…"
        spellCheck={false}
      />
      <ExecOutput state={state} />
    </div>
  );
}

function ExecOutput({ state }: { state: ExecState }) {
  if (state.kind === 'idle') return null;
  if (state.kind === 'running') {
    return <div className="text-sm text-muted">等待用户批准…</div>;
  }
  if (state.kind === 'denied') {
    return (
      <div className="text-sm text-amber-700 bg-amber-50 px-3 py-2 rounded">
        权限被拒绝: {state.message}
      </div>
    );
  }
  if (state.kind === 'error') {
    return (
      <div className="space-y-2">
        <div className="text-sm text-red-700 bg-red-50 px-3 py-2 rounded">
          执行失败: {state.message}
        </div>
        {state.result && <ExecResultBody result={state.result} tone="error" />}
      </div>
    );
  }
  // success
  return (
    <div className="space-y-1">
      <ExecResultBody result={state.result} tone="success" />
    </div>
  );
}

function ExecResultBody({ result, tone }: { result: ExecResultView; tone: 'success' | 'error' }) {
  // 退出码 / 超时 / 截断 / 耗时 —— 成功与失败路径共用。
  // 超时和信号杀死时 exitCode 为 null，分别显示为「执行超时」和「被信号终止」。
  const exitLabel = result.timedOut
    ? '执行超时（进程已被终止）'
    : result.exitCode === null
      ? '无退出码（进程被信号终止或未启动）'
      : `退出码 ${result.exitCode}`;
  return (
    <>
      <div className="text-xs text-muted">
        <span className={tone === 'error' ? 'text-red-600' : undefined}>{exitLabel}</span>
        {' · '}耗时 {result.duration.toFixed(2)}s
        {result.outputTruncated && (
          <span className="ml-2 text-amber-700" title="单个流（stdout / stderr）超过 64 KiB 被截断">
            ⚠ 输出已截断
          </span>
        )}
      </div>
      {result.error && (
        <div className="text-sm text-red-600" title="子进程报告的致命错误（如 spawn 失败、超时）">
          错误: {result.error}
        </div>
      )}
      {result.command && result.command.length > 0 && tone === 'error' && (
        <div className="text-[11px] text-muted font-mono truncate" title={result.command.join(' ')}>
          命令: {result.command.join(' ')}
        </div>
      )}
      {result.stdout && (
        <pre className="text-xs font-mono bg-bg-muted px-2 py-1 rounded whitespace-pre-wrap">
          {result.stdout}
        </pre>
      )}
      {result.stderr && (
        <pre className="text-xs font-mono bg-red-50 text-red-700 px-2 py-1 rounded whitespace-pre-wrap">
          {result.stderr}
        </pre>
      )}
    </>
  );
}
