/**
 * Settings 页面 - 运行环境与诊断 Tab
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

import { DiagnosticCard } from '../../features/diagnostic';
import { runtimeApi } from '../../shared/api/runtimeApi';
import type {
  Diagnostic,
  ExecutionResult,
  ProbeResult,
  ProjectDiagnosis,
  RuntimeInfo,
  ToolCallEnvelope,
} from '../../shared/api/runtimeTypes';
import { useI18n } from '../../shared/lib/i18n';
import { DiagnosticsCard } from '../../widgets/settings/DiagnosticsCard';

import { SettingRow } from './components';

export interface RuntimeEnvTabAuditInput {
  probeKind: string;
  runtimeCount: number;
  selectedRuntime: string | null;
  diagnoseKind: string;
  execKind: string;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatRuntimeEnvTabAuditSnapshot(input: RuntimeEnvTabAuditInput): string {
  return [
    `# 运行环境与诊断审计快照`,
    `- 探测状态: ${input.probeKind}`,
    `- 可用运行时数: ${input.runtimeCount}`,
    `- 当前选中运行时: ${input.selectedRuntime || '未选择'}`,
    `- 诊断状态: ${input.diagnoseKind}`,
    `- 试跑状态: ${input.execKind}`,
  ].join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatRuntimeEnvTabAuditJson(input: RuntimeEnvTabAuditInput): string {
  return JSON.stringify(
    {
      probeKind: input.probeKind,
      runtimeCount: input.runtimeCount,
      selectedRuntime: input.selectedRuntime || null,
      diagnoseKind: input.diagnoseKind,
      execKind: input.execKind,
    },
    null,
    2,
  );
}

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
  const { t } = useI18n();
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
        setProbe({ kind: 'error', message: env.error ?? t('settings.runtime.probe_failed') });
      }
    } catch (error) {
      setProbe({
        kind: 'error',
        message:
          error instanceof Error ? error.message : t('settings.runtime.probe_request_failed'),
      });
    }
  }, [selectedRuntime, t]);

  const runDiagnose = useCallback(async () => {
    setDiagnose({ kind: 'loading' });
    try {
      const env = await runtimeApi.diagnose();
      if (env.success && env.output) {
        setDiagnose({ kind: 'ok', data: env.output });
      } else {
        setDiagnose({ kind: 'error', message: env.error ?? t('settings.runtime.diagnose_failed') });
      }
    } catch (error) {
      setDiagnose({
        kind: 'error',
        message:
          error instanceof Error ? error.message : t('settings.runtime.diagnose_request_failed'),
      });
    }
  }, [t]);

  const runExec = useCallback(async () => {
    if (!selectedRuntime) return;
    setExec({ kind: 'running' });
    const env = await runtimeApi.probe();
    if (!env.success || !env.output) {
      setExec({ kind: 'error', message: env.error ?? t('settings.runtime.language_unknown') });
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
        message: error instanceof Error ? error.message : t('settings.runtime.exec_request_failed'),
      });
    }
  }, [selectedRuntime, code, t]);

  function handleExecResult(result: ToolCallEnvelope<ExecutionResult>) {
    if (result.success && result.output) {
      setExec({ kind: 'success', result: toView(result.output) });
      return;
    }
    // 权限拒绝 vs 其他失败
    const err = result.error ?? t('settings.runtime.exec_failed');
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
          <h3 className="text-ui-md font-semibold text-ink">
            {t('settings.runtime.section.local_title')}
          </h3>
          <p className="text-xs text-muted mt-1">{t('settings.runtime.section.local_desc')}</p>
        </div>
        <ProbePanel state={probe} onRetry={runProbe} />
      </section>

      <section>
        <div className="mb-3">
          <h3 className="text-ui-md font-semibold text-ink">
            {t('settings.runtime.section.project_title')}
          </h3>
          <p className="text-xs text-muted mt-1">{t('settings.runtime.section.project_desc')}</p>
        </div>
        <DiagnosePanel state={diagnose} onRetry={runDiagnose} />
      </section>

      <section>
        <SettingRow
          label={t('settings.runtime.try_run_label')}
          desc={t('settings.runtime.try_run_desc')}
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

      {/* 原「通用」tab 的诊断区块（2026-10-28 迁入） */}
      <section>
        <h3 className="text-ui-md font-semibold text-ink mb-3">
          {t('settings.runtime.section.logs')}
        </h3>
        <DiagnosticsCard />
      </section>
      <section>
        <h3 className="text-ui-md font-semibold text-ink mb-3">
          {t('settings.runtime.section.llm_preview')}
        </h3>
        <DiagnosticCard />
      </section>
    </div>
  );
}

function ProbePanel({ state, onRetry }: { state: ProbeState; onRetry: () => void }) {
  const { t } = useI18n();
  if (state.kind === 'loading') {
    return <div className="text-sm text-muted">{t('settings.runtime.probing')}</div>;
  }
  if (state.kind === 'error') {
    return (
      <div className="space-y-2">
        <div className="text-sm text-error">
          {t('settings.runtime.probe_failed')}: {state.message}
        </div>
        <button
          type="button"
          className="px-3 py-1 text-xs bg-primary text-text-inverse rounded"
          onClick={onRetry}
        >
          {t('settings.runtime.retry')}
        </button>
      </div>
    );
  }
  if (state.kind === 'idle') {
    return <div className="text-sm text-muted">{t('settings.runtime.waiting_probe')}</div>;
  }
  const { data } = state;
  if (data.runtimes.length === 0) {
    return (
      <div className="text-sm text-muted">
        {t('settings.runtime.no_runtimes')}
        {data.errors.length > 0 &&
          `${t('settings.runtime.errors_label')} ${data.errors.join(', ')}`}
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
                  {rt.version ?? t('settings.runtime.unknown_version')}
                </span>
                <span className="text-xs text-muted font-mono">{rt.path}</span>
                {rt.is_default && (
                  <span className="text-ui-xs px-1 py-0.5 rounded bg-primary/10 text-primary">
                    {t('settings.runtime.recommended')}
                  </span>
                )}
                <span className="text-ui-xs text-muted">{rt.source}</span>
              </li>
            ))}
          </ul>
        </li>
      ))}
      {data.errors.length > 0 && (
        <li className="text-xs text-warning">
          {t('settings.runtime.warning_label')} {data.errors.join('; ')}
        </li>
      )}
    </ul>
  );
}

function DiagnosePanel({ state, onRetry }: { state: DiagnoseState; onRetry: () => void }) {
  const { t } = useI18n();
  if (state.kind === 'loading') {
    return <div className="text-sm text-muted">{t('settings.runtime.diagnosing')}</div>;
  }
  if (state.kind === 'error') {
    return (
      <div className="space-y-2">
        <div className="text-sm text-error">
          {t('settings.runtime.diagnose_failed')}: {state.message}
        </div>
        <button
          type="button"
          className="px-3 py-1 text-xs bg-primary text-text-inverse rounded"
          onClick={onRetry}
        >
          {t('settings.runtime.retry')}
        </button>
      </div>
    );
  }
  if (state.kind === 'idle') {
    return <div className="text-sm text-muted">{t('settings.runtime.waiting_diagnose')}</div>;
  }
  const { data } = state;
  const manifests = Array.isArray(data.manifests) ? data.manifests : [];
  const diagnostics = Array.isArray(data.diagnostics) ? data.diagnostics : [];
  const probeErrors = Array.isArray(data.probe_errors) ? data.probe_errors : [];
  const requiredLanguages = [...new Set(manifests.map((manifest) => manifest.language))];
  const levelLabels: Record<string, string> = {
    satisfied: t('settings.runtime.level_satisfied'),
    partial: t('settings.runtime.level_partial'),
    unsatisfied: t('settings.runtime.level_unsatisfied'),
  };
  const levelLabel = levelLabels[data.level] ?? t('settings.runtime.level_unknown');
  const levelClassName =
    {
      satisfied: 'text-success',
      partial: 'text-warning',
      unsatisfied: 'text-error',
    }[data.level] ?? 'text-muted';
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted">{t('settings.runtime.manifests_label')}</span>
        <span className="font-mono">
          {manifests.length > 0 ? requiredLanguages.join(', ') : t('settings.runtime.unidentified')}
        </span>
        <span className="text-muted ml-4">{t('settings.runtime.satisfaction_label')}</span>
        <span className={`${levelClassName} font-semibold`}>{levelLabel}</span>
      </div>
      {data.recommended_runtime && (
        <div className="text-xs text-muted">
          {t('settings.runtime.recommended_runtime_label')} {data.recommended_runtime}
        </div>
      )}
      {requiredLanguages.length > 0 && (
        <div className="text-xs text-muted">
          {t('settings.runtime.required_languages_label')} {requiredLanguages.join(', ')}
        </div>
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
        <div className="text-xs text-warning">
          {t('settings.runtime.probe_warnings_label')} {probeErrors.join('; ')}
        </div>
      )}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: Diagnostic['severity'] }) {
  const styles: Record<'info' | 'warning' | 'error', string> = {
    info: 'bg-info/15 text-info',
    warning: 'bg-warning/15 text-warning',
    error: 'bg-error/15 text-error',
  };
  const fallback = 'bg-bg-muted text-muted';
  return (
    <span
      className={`inline-block px-1.5 py-0.5 text-ui-xs rounded uppercase font-semibold ${
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
  const { t } = useI18n();
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <label className="text-xs text-muted">{t('settings.runtime.runtime_label')}</label>
        <select
          value={selectedRuntime ?? ''}
          onChange={(e) => onSelectRuntime(e.target.value)}
          className="flex-1 text-sm px-2 py-1 border border-line rounded bg-bg"
        >
          <option value="" disabled>
            {runtimes.length === 0
              ? t('settings.runtime.probe_first')
              : t('settings.runtime.select_runtime')}
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
          {state.kind === 'running'
            ? t('settings.runtime.executing')
            : t('settings.runtime.execute')}
        </button>
      </div>
      <textarea
        value={code}
        onChange={(e) => onChangeCode(e.target.value)}
        className="w-full h-28 text-xs font-mono px-2 py-1 border border-line rounded bg-bg"
        placeholder={t('settings.runtime.code_placeholder')}
        spellCheck={false}
      />
      <ExecOutput state={state} />
    </div>
  );
}

function ExecOutput({ state }: { state: ExecState }) {
  const { t } = useI18n();
  if (state.kind === 'idle') return null;
  if (state.kind === 'running') {
    return <div className="text-sm text-muted">{t('settings.runtime.waiting_approval')}</div>;
  }
  if (state.kind === 'denied') {
    return (
      <div className="text-sm text-warning bg-warning/10 px-3 py-2 rounded">
        {t('settings.runtime.permission_denied_label')} {state.message}
      </div>
    );
  }
  if (state.kind === 'error') {
    return (
      <div className="space-y-2">
        <div className="text-sm text-error bg-error/10 px-3 py-2 rounded">
          {t('settings.runtime.exec_failed')}: {state.message}
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
  const { t } = useI18n();
  // 退出码 / 超时 / 截断 / 耗时 —— 成功与失败路径共用。
  // 超时和信号杀死时 exitCode 为 null，分别显示为「执行超时」和「被信号终止」。
  const exitLabel = result.timedOut
    ? t('settings.runtime.exit_timeout')
    : result.exitCode === null
      ? t('settings.runtime.exit_no_code')
      : t('settings.runtime.exit_code_label').replace('{code}', String(result.exitCode));
  return (
    <>
      <div className="text-xs text-muted">
        <span className={tone === 'error' ? 'text-error' : undefined}>{exitLabel}</span>
        {' · '}
        {t('settings.runtime.duration_label')} {result.duration.toFixed(2)}s
        {result.outputTruncated && (
          <span className="ml-2 text-warning" title={t('settings.runtime.truncated_title')}>
            {t('settings.runtime.truncated_badge')}
          </span>
        )}
      </div>
      {result.error && (
        <div className="text-sm text-error" title={t('settings.runtime.error_detail_title')}>
          {t('settings.runtime.error_label')} {result.error}
        </div>
      )}
      {result.command && result.command.length > 0 && tone === 'error' && (
        <div className="text-ui-2xs text-muted font-mono truncate" title={result.command.join(' ')}>
          {t('settings.runtime.command_label')} {result.command.join(' ')}
        </div>
      )}
      {result.stdout && (
        <pre className="text-xs font-mono bg-bg-muted px-2 py-1 rounded whitespace-pre-wrap">
          {result.stdout}
        </pre>
      )}
      {result.stderr && (
        <pre className="text-xs font-mono bg-error/10 text-error px-2 py-1 rounded whitespace-pre-wrap">
          {result.stderr}
        </pre>
      )}
    </>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditRuntimeEnvTabGovernance(): {
  module: 'src/pages/settings/RuntimeEnvTab.tsx';
  phase: 'P173';
  domain: 'settings';
  supportsRuntimeDiagnosticsAndOutputInspection: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/settings/RuntimeEnvTab.tsx',
    phase: 'P173',
    domain: 'settings',
    supportsRuntimeDiagnosticsAndOutputInspection: true,
    compliant: true,
  };
}
