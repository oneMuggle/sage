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

type ExecState =
  | { kind: 'idle' }
  | { kind: 'running' }
  | { kind: 'error'; message: string }
  | { kind: 'denied'; message: string }
  | { kind: 'success'; stdout: string; stderr: string; exitCode: number; duration: number };

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

  function handleExecResult(
    result: ToolCallEnvelope<{
      exit_code: number;
      stdout: string;
      stderr: string;
      duration_seconds: number;
    }>,
  ) {
    if (result.success && result.output) {
      setExec({
        kind: 'success',
        stdout: result.output.stdout,
        stderr: result.output.stderr,
        exitCode: result.output.exit_code,
        duration: result.output.duration_seconds,
      });
    } else {
      // 权限拒绝 vs 其他失败
      const err = result.error ?? '执行失败';
      if (err.includes('权限') || err.includes('Permission') || err.includes('denied')) {
        setExec({ kind: 'denied', message: err });
      } else {
        setExec({ kind: 'error', message: err });
      }
    }
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
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted">项目类型:</span>
        <span className="font-mono">{data.project_type}</span>
        <span className="text-muted ml-4">满足度:</span>
        {data.satisfied ? (
          <span className="text-green-600 font-semibold">✓ 全部满足</span>
        ) : (
          <span className="text-amber-600 font-semibold">⚠ 需要处理</span>
        )}
      </div>
      {data.required_languages.length > 0 && (
        <div className="text-xs text-muted">需要的语言: {data.required_languages.join(', ')}</div>
      )}
      {data.diagnostics.length > 0 && (
        <ul className="space-y-1">
          {data.diagnostics.map((d: Diagnostic, i: number) => (
            <li key={i} className="text-sm">
              <SeverityBadge severity={d.severity} />
              <span className="ml-2 font-mono text-xs text-muted">{d.code}</span>
              <span className="ml-2">{d.message}</span>
              {d.fix_hint && <span className="ml-2 text-xs text-primary">{d.fix_hint}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: Diagnostic['severity'] }) {
  const styles = {
    info: 'bg-blue-100 text-blue-700',
    warn: 'bg-amber-100 text-amber-700',
    error: 'bg-red-100 text-red-700',
  } as const;
  return (
    <span
      className={`inline-block px-1.5 py-0.5 text-[10px] rounded uppercase font-semibold ${styles[severity]}`}
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
      <div className="text-sm text-red-700 bg-red-50 px-3 py-2 rounded">
        执行失败: {state.message}
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted">
        退出码 {state.exitCode} · 耗时 {state.duration.toFixed(2)}s
      </div>
      {state.stdout && (
        <pre className="text-xs font-mono bg-bg-muted px-2 py-1 rounded whitespace-pre-wrap">
          {state.stdout}
        </pre>
      )}
      {state.stderr && (
        <pre className="text-xs font-mono bg-red-50 text-red-700 px-2 py-1 rounded whitespace-pre-wrap">
          {state.stderr}
        </pre>
      )}
    </div>
  );
}
